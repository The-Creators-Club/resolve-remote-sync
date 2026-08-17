<!-- DRAFT FOR COUNSEL — NOT LEGAL ADVICE, NOT YET EXECUTABLE.
     Written 2026-08-17 for docs/COMMERCIAL_READINESS.md item 3. Every clause
     here is an engineer's description of what the software actually does,
     shaped into contract form so a lawyer has something concrete to redline.
     It has NOT been reviewed by a qualified legal professional.
     TODO(legal): replace "Cablewrap Creative" with the registered legal
     entity name, its company number and registered address. The placeholder
     was taken from the operator's email domain and is
     almost certainly NOT the correct contracting entity — confirm before use.
     TODO(legal): set the governing-law jurisdiction (marked below).
     TODO(legal): confirm the EULA-VERSION bump policy in docs/legal/README
     before changing the version marker — bumping it forces every editor in
     every customer fleet through the acceptance wizard again. -->

<!-- EULA-VERSION: 1.0 -->

# CC Sync — End User Licence Agreement

**Version 1.0 — draft of 2026-08-17. DRAFT FOR COUNSEL.**

This End User Licence Agreement ("Agreement") is between **Cablewrap Creative**
(the "Licensor") and the individual or organisation installing or using the
CC Sync software (the "Customer", "you").

By clicking ACCEPT in the CC Sync setup wizard, or by installing, copying or
using any part of the Software, you agree to this Agreement. If you do not
agree, do not install or use the Software.

## 1. What the Software is

"Software" means the CC Sync fleet-sync system, including the CC Sync
companion tray application, the CC Sync fleet dashboard, the b-roll and music
search applications, the setup wizard and installer, the server-side
provisioning scripts, and any documentation and updates supplied under this
Agreement.

The Software coordinates media files between a customer-operated network
storage server and the workstations of the customer's video editors, and
automates parts of the editing workflow.

## 2. Licence grant

Subject to your compliance with this Agreement and payment of any applicable
fees, the Licensor grants you a non-exclusive, non-transferable,
non-sublicensable, revocable licence to install and use the Software on the
number of workstations and servers covered by your order, for your internal
business purposes only, for the term of your subscription or licence.

## 3. Restrictions

You must not:

a. copy, distribute, sell, rent, lease, sublicense or otherwise make the
   Software available to any third party, except as expressly permitted here;
b. reverse engineer, decompile or disassemble the Software, or attempt to
   derive its source code, except to the extent that applicable law expressly
   permits this notwithstanding this restriction, and except in respect of
   third-party components licensed to you under terms that grant those rights
   (see section 11);
c. remove, obscure or alter any copyright, trademark or other proprietary
   notice in the Software;
d. use the Software to build a competing product or service;
e. use the Software other than in accordance with the documentation, or in
   any way that breaches the terms of the third-party products it interoperates
   with (see section 5).

## 4. Ownership

The Software is licensed, not sold. The Licensor and its suppliers retain all
right, title and interest in and to the Software, including all intellectual
property rights. No rights are granted other than those expressly stated here.

## 5. Third-party requirements — DaVinci Resolve Studio

The Software is designed for use with **DaVinci Resolve®** and **requires
DaVinci Resolve Studio** (the paid edition) on each editing workstation whose
projects it manages: the free edition of DaVinci Resolve does not expose the
external scripting interface the Software depends on.

DaVinci Resolve and DaVinci Resolve Studio are products of **Blackmagic Design
Pty Ltd**, are not supplied under this Agreement, and are licensed to you
separately by Blackmagic Design. You are responsible for holding valid licences
for them and for complying with their terms, including any terms governing
scripting and automation.

The Licensor is not affiliated with, endorsed by or sponsored by Blackmagic
Design. "DaVinci Resolve" and "Blackmagic Design" are trademarks of Blackmagic
Design Pty Ltd, used here for identification only.

Other third-party products the Software interoperates with — including
Tailscale, Syncthing, rclone and, where enabled, network media services — are
licensed to you by their own suppliers under their own terms, which you are
responsible for meeting. Some of them require a paid plan at your scale.

## 6. Customer data and content

You retain all rights in the video, audio, LUTs, project files and other
content you process with the Software ("Customer Content"). The Licensor
claims no ownership of it.

The Software operates on infrastructure you control. Customer Content is stored
on your storage server and your workstations; the Licensor does not receive it
in the ordinary course of operating the Software.

You warrant that you hold the rights necessary to store, copy and process the
Customer Content with the Software, including any music, stock footage or LUT
packs you distribute to your editors through it, and you will indemnify the
Licensor against third-party claims arising from Customer Content.

## 7. Operational data and monitoring — READ THIS

The CC Sync companion running on each editing workstation reports operational
data to the CC Sync dashboard on **your own server**, several times a minute.
That data identifies the workstation and its user, and includes **the name of
the DaVinci Resolve project currently open on that workstation**, an inventory
of the media files present locally, and the project's bin structure.

**This is capable of being used to monitor individual employees or
contractors.** It is visible to whoever administers your dashboard. If you
deploy the Software, **you** are the data controller for that data, and you —
not the Licensor — are responsible for having a lawful basis for it, for
informing the people it describes, and for meeting your obligations under the
UK GDPR, the EU GDPR and any other applicable data-protection law.

`docs/legal/TELEMETRY.md` states exactly what is reported, how often, who can
see it, how long it is kept, and what can be switched off. Read it before
deploying. `docs/legal/PRIVACY.md` states what, if anything, reaches the
Licensor.

## 8. Support, updates and the upgrade channel

Support and updates are provided as described in your order or support plan.
The Software includes an upgrade channel that installs new companion builds
published to your own dashboard by your own administrator. The Licensor does
not push software to your workstations directly.

## 9. Warranty disclaimer

TO THE MAXIMUM EXTENT PERMITTED BY LAW, THE SOFTWARE IS PROVIDED "AS IS" AND
"AS AVAILABLE", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NON-INFRINGEMENT. THE LICENSOR DOES NOT WARRANT THAT THE SOFTWARE WILL BE
UNINTERRUPTED OR ERROR-FREE.

**THE SOFTWARE MOVES, RENAMES AND DELETES FILES.** It is a synchronisation and
automation tool, not a backup product. You are responsible for maintaining
independent, tested backups of all Customer Content. Nothing in the Software
substitutes for a backup.

## 10. Limitation of liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, THE LICENSOR WILL NOT BE LIABLE FOR ANY
INDIRECT, INCIDENTAL, SPECIAL OR CONSEQUENTIAL DAMAGES, OR FOR ANY LOSS OF
PROFITS, REVENUE, DATA, MEDIA OR GOODWILL, ARISING OUT OF OR RELATED TO THIS
AGREEMENT OR THE SOFTWARE. THE LICENSOR'S TOTAL AGGREGATE LIABILITY WILL NOT
EXCEED THE FEES PAID BY YOU FOR THE SOFTWARE IN THE TWELVE MONTHS PRECEDING THE
EVENT GIVING RISE TO THE CLAIM.

Nothing in this Agreement excludes or limits liability for death or personal
injury caused by negligence, for fraud, or for any other liability that cannot
lawfully be excluded.

## 11. Third-party open-source components

The Software includes third-party components licensed under their own terms,
listed in `docs/legal/THIRD_PARTY_NOTICES.md`. Where a component's licence
grants you rights that conflict with this Agreement — including rights to the
component's source code, or to reverse engineer it — that licence prevails for
that component.

Certain components are licensed under the GNU General Public Licence. Where the
Licensor or its installer conveys such a component to you in binary form, you
are entitled to the corresponding source code on the terms stated in
`docs/legal/THIRD_PARTY_NOTICES.md`.

## 12. Term and termination

This Agreement runs for the term of your licence or subscription. The Licensor
may terminate it if you materially breach it and do not cure the breach within
30 days of written notice. On termination you must stop using the Software and
remove it from your systems. Sections 4, 6, 9, 10 and 13 survive termination.

## 13. General

This Agreement is governed by the laws of **[TODO(legal): jurisdiction]**, and
the courts of that jurisdiction have exclusive jurisdiction over disputes
arising from it. If any provision is held unenforceable, the rest remains in
effect. This Agreement, together with your order, is the entire agreement
between the parties in respect of the Software.

Export controls: you must not use or export the Software in breach of any
applicable export-control or sanctions law.

## 14. Contact

**Cablewrap Creative** — TODO(legal): registered entity name, company number,
registered address, contact email, and a security contact address for
vulnerability reports.
