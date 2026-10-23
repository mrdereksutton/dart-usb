# 2016 Dart Uconnect 8.4/8.4N target

Optimize the dongle's USB/iPod behavior for the existing Uconnect player. The
first product target is wireless music, accurate now-playing text and working
playback controls. Record the radio's exact model, part number and software
version when available; those details are not yet captured locally. Changes to
head-unit firmware are not needed for the current implementation.

## Acceptance checks

| Car behavior | Firmware/test requirement |
| --- | --- |
| USB source starts playback | Capture actual enumeration, iAP identification/authentication and audio activation; verify the accepted configuration/alternate/rate |
| Track number, elapsed time and Info | Coherent title/artist/album/index/duration/state; test updates, pause/resume and missing metadata |
| Next/previous arrows | Match the car's actual requests, including restart-current-track versus previous-track behavior |
| Held arrows seek | Capture press/release and reflect confirmed phone seek position |
| Repeat/shuffle | Translate requested mode and report the phone player's resulting state |
| Browse by artist/album/song/playlist | Expose only a catalog the phone-side transport can actually provide/control |
| Steering-wheel buttons | Capture requests separately from touchscreen buttons and preserve factory volume/source behavior |
| Ignition and source changes | Reconnect, drain old audio, clear stale metadata and resume predictably |

The Dart-specific manual documents these player/browse destinations; it does not
specify the car's USB descriptor choices, iAP handshake or authentication policy.
Those require a real car transaction log. Generic UAC support remains an open
compatibility question.

During metadata validation, set **Music Info Cleanup off**: the manual says its
Gracenotes lookup can normalize displayed song/artist/album text. This makes our
sent strings easier to compare with the screen. Recheck normal operation with
the user's preferred setting afterward. Exact artwork behavior remains a separate
car test.

The useful first car session is a short ordered check: USB recognition, stable
test audio, known title/artist/album, then next/previous/play/pause. Extend into
browsing and ignition cycles once those work. Moving the stock dongle to the car
now would remove its Mac programming connection; the current RAM trial also clears
on power loss and has no standalone Bluetooth receiver yet.

Primary reference: [2016 Dart Uconnect 8.4/8.4N supplement](https://vehicleinfo.mopar.com/assets/publications/en-us/Dodge/2016/Dart/1104.pdf),
printed page 28 (Music Info Cleanup) and pages 38–43 (USB operation and browsing).
