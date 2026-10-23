"""Verify the observed CU image format without opening USB or writing flash.

Field layout matches Realtek's related patch_header_check.h. Each checksum and
RSA-PSS span below is independently checked against actual CU images.
RSA-PSS follows RFC 8017 section 9.1.2 with SHA-256. Observed salt lengths
are 32 bytes in the CU images and 222 bytes in the re-signed SDK stack.
"""
import hashlib,hmac,struct
HEADER_SIZE=0x400
FLASH_BASE=0x02000000
PUBLIC_KEY_SHA256='d3e58130d78decc7c05aebf09ac8a9165f02704b935cfbe567fdca0e60341196'
IMAGE_NAMES={0x2790:'OTA header',0x2791:'secondary bootloader',0x2793:'MCU application',
    0x2794:'DSP system',0x2795:'DSP application',0x2796:'MCU configuration',
    0x279c:'system patch',0x279d:'stack patch',0x27a3:'preinstalled upper stack'}

def crc16_ibm(data):
    table=[]
    for byte in range(256):
        value=byte
        for _ in range(8):value=(value>>1)^(0xa001 if value&1 else 0)
        table.append(value)
    value=0
    for byte in data:value=(value>>8)^table[(value^byte)&255]
    return value

def rsa_pss_salt_length(image):
    n=int.from_bytes(image[0x1a0:0x2a0],'big');e=int.from_bytes(image[0x2a0:0x2a4],'big')
    signature=int.from_bytes(image[0x10:0x110],'big')
    if n.bit_length()!=2048 or not n&1 or e!=65537 or signature>=n:return None
    encoded=pow(signature,e,n).to_bytes(256,'big')
    if encoded[-1]!=0xbc or encoded[0]&0x80:return None
    hashed=encoded[-33:-1]
    mask=b''.join(hashlib.sha256(hashed+i.to_bytes(4,'big')).digest() for i in range(7))[:223]
    decoded=bytearray(x^y for x,y in zip(encoded[:223],mask));decoded[0]&=0x7f
    first=next((index for index,value in enumerate(decoded) if value),None)
    if first is None or decoded[first]!=1:return None
    salt=decoded[first+1:]
    # The signature covers the stored image hash followed by control/header/payload.
    message_hash=hashlib.sha256(image[0x110:]).digest()
    expected=hashlib.sha256(bytes(8)+message_hash+salt).digest()
    return len(salt) if hmac.compare_digest(hashed,expected) else None

def rsa_pss_valid(image):return rsa_pss_salt_length(image) is not None

def verify_image(data):
    if len(data)<HEADER_SIZE:raise ValueError('Truncated CU image header')
    crc,chip,secure,flags,ident,length=struct.unpack_from('<HBBHHI',data,0x130)
    if chip!=0x0b or ident not in IMAGE_NAMES:raise ValueError('Unrecognized CU image control header')
    end=HEADER_SIZE+length
    if end>len(data) or end>0x200000:raise ValueError('Image payload exceeds available bytes')
    image=bytes(data[:end]);key=hashlib.sha256(image[0x1a0:0x2a4]).hexdigest();salt=rsa_pss_salt_length(image)
    report={'image_id':ident,'name':IMAGE_NAMES[ident],'image_bytes':end,'payload_bytes':length,
        'crc16':crc,'crc16_valid':crc16_ibm(image[0x132:])==crc,
        'sha256_valid':hmac.compare_digest(hashlib.sha256(image[0x130:]).digest(),image[0x110:0x130]),
        'rsa_pss_valid':salt is not None,'rsa_pss_salt_bytes':salt,'public_key_sha256':key,'known_key':key==PUBLIC_KEY_SHA256,
        'flags':flags,'xip':bool(flags&1),'encrypted':bool(flags&2),'load_when_boot':bool(flags&4),
        'not_ready':bool(flags&0x80),'not_obsolete':bool(flags&0x100),'integrity_check_in_boot':bool(flags&0x200),
        'secure_version':secure,'execute':struct.unpack_from('<I',image,0x14c)[0],
        'load_source':struct.unpack_from('<I',image,0x150)[0],'load_length':struct.unpack_from('<I',image,0x154)[0],
        'image_base':struct.unpack_from('<I',image,0x158)[0],
        'sha256':hashlib.sha256(image).hexdigest(),'header_sha256':hashlib.sha256(image[:HEADER_SIZE]).hexdigest()}
    report['verified']=all(report[k] for k in ('crc16_valid','sha256_valid','rsa_pss_valid'))
    return report

def partitions(ota_image):
    report=verify_image(ota_image)
    if report['image_id']!=0x2790 or not report['verified']:raise ValueError('Verified OTA header required')
    result=[]
    for index in range(16):
        address,size=struct.unpack_from('<II',ota_image,0x2a8+index*8)
        if not address and not size:continue
        if address<FLASH_BASE or not size or address+size>FLASH_BASE+0x200000:raise ValueError('OTA partition outside captured flash window')
        result.append({'image_id':0x2791+index,'name':IMAGE_NAMES.get(0x2791+index,'other'),
            'cpu_address':address,'cpu_view_offset':address-FLASH_BASE,'size':size})
    ordered=sorted(result,key=lambda p:p['cpu_address'])
    if any(a['cpu_address']+a['size']>b['cpu_address'] for a,b in zip(ordered,ordered[1:])):raise ValueError('Overlapping OTA partitions')
    return result
