# Synology day-1 spikes — run against real hardware, 2026-08-17

The eight spikes from `SYNOLOGY_PORT_PLAN.md` ("Day-1 spikes on the device"),
executed against a live DSM box. Everything below is measured, not inferred;
where something could not be determined it says so and why.

**Read this before writing WP2 or WP3 code.** Four of the eight spikes came
back differently from what the plan assumed, and one (spike 6) found a defect
in the *existing shipped companion tuning* that would silently truncate every
lane-B download from a Synology NAS.

## The device

| | |
|---|---|
| Model / CPU | `synology_geminilake_423+` (DS423+), Celeron J4125, x86_64, 4 cores |
| DSM | 7.2.1-69057 Update 6 (`productversion=7.2.1`, `smallfixnumber=6`, built 2024/11/11) |
| Kernel | 4.4.302+ |
| Volume | `/volume1`, Btrfs on `/dev/mapper/cachedev_0`, 21 TB, **~60 GB free** |
| Network | LAN `192.168.0.104` (1 GbE), tailnet `100.65.15.123` = `nas.tail26290e.ts.net` |
| Tailscale | package 1.58.2, `TUN: true`, subnet router for `192.168.0.0/24` + exit node |
| Container Manager | docker 24.0.2, compose v2.20.1, 11 pre-existing CLI/UI stacks |
| OpenSSH | **8.2p1** / OpenSSL 1.1.1u — matters, see spike 6 |
| Uptime at test | 77 days |
| Admin used | `Cablewrap` (uid 1026, member of `administrators`), password on stdin to `sudo -S` |

This is a **live production NAS** with other people's stacks (jellyfin, *arr,
umami, plex, claude-code). Everything done here was additive and prefixed
`ccsync`; the "Left on the device" and "Removed" inventories at the bottom are
exhaustive.

**PATH note that cost the first ten minutes:** the Synology CLIs are not on
`sudo`'s PATH on this box. Every remote command in this document was run as:

```sh
sudo -S -p '' sh -c 'export PATH=/usr/syno/bin:/usr/syno/sbin:/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin; <cmd>'
```

with the password written to stdin. WP3's generated remote scripts must do the
same or `synoshare`/`synoacltool`/`synowebapi` are simply "not found".

---

## Spike 1 — synoacl vs POSIX mode bits

### What was run

The share was created through the Web API (spike 3) and its group permission
set the same way:

```
SYNO.Core.Share create   name=CCSyncTest shareinfo={"name":"CCSyncTest","vol_path":"/volume1",...}
SYNO.Core.Share.Permission set  name=CCSyncTest user_group_type=local_group
        permissions=[{"name":"editors","is_readonly":false,"is_writable":true,...}]
```

That alone produced the inheritable ACE the plan wanted to add by hand:

```
$ synoacltool -get /volume1/CCSyncTest
ACL version: 1
Archive: has_ACL,is_support_ACL
Owner: [root(user)]
	 [0] group:administrators:allow:rwxpdDaARWc--:fd-- (level:0)
	 [1] group:editors:allow:rwxpdDaARWc--:fd-- (level:0)

$ ls -lnd /volume1/CCSyncTest
d---------+ 1 0 0 12 Aug 17 13:39 /volume1/CCSyncTest
```

Mode bits `0000`, owner `root`, and yet both editors have full access. That is
the headline.

Cross-write, `ccsync_a` over SFTP creating `Projects/demo/sub/` + a file, then
`ccsync_b` doing everything to it — over SFTP:

```
mkdir OK /CCSyncTest/Projects ; /CCSyncTest/Projects/demo ; /CCSyncTest/Projects/demo/sub
write a_sftp.txt OK
-- ccsync_b over SFTP into A's dir --
B create file: OK
B rename A's file: OK
B append to A's file: OK
B mkdir in A's dir: OK
```

…and over SMB (`net use \\192.168.0.104\CCSyncTest /user:ccsync_b <pw>`):

```
B create b_smb.txt : OK
B append to A's file : OK
B rename A's file : OK
B mkdir b_smb_dir : OK
B delete own b_sftp.txt : OK
B rmdir A-created b_dir : OK
```

Windows' own view of the effective ACL on that directory:

```
S-1-5-...-1203   Allow DeleteSubdirectoriesAndFiles, Modify, Synchronize inherit=ContainerInherit, ObjectInherit
S-1-5-...-132073 Allow DeleteSubdirectoriesAndFiles, Modify, Synchronize inherit=ContainerInherit, ObjectInherit
```

(RID 132073 = gid 65536 `editors`; DSM maps gid→RID as `gid*2 + 1001`.)

Inheritance depth is tracked and correct — the `(level:N)` counter increments
per directory, and files get the non-inheritable copy:

```
$ synoacltool -get /volume1/CCSyncTest/Projects/demo/sub
	 [0] group:administrators:allow:rwxpdDaARWc--:fd-- (level:3)
	 [1] group:editors:allow:rwxpdDaARWc--:fd-- (level:3)
$ synoacltool -get .../sub/b_sftp.txt
	 [1] group:editors:allow:rwxpdDaARWc--:---- (level:4)
$ ls -lnR /volume1/CCSyncTest/Projects/demo/sub
----------+ 1 1030 100 68 a_smb_renamed.txt
----------+ 1 1031 100 30 b_smb.txt
d---------+ 1 1031 100  0 b_smb_dir
```

Every mode bit is zero. Every operation works.

### The `chmod` result — this is the dangerous one

```
$ chown root:editors /volume1/CCSyncTest/posixtest
$ chmod 2770        /volume1/CCSyncTest/posixtest
$ ls -land ...      ->  drwxrws--- 1 0 65536 ...        (note: no "+")
$ synoacltool -get ...
(synoacltool.c, 596)It's Linux mode
$ synoacltool -get-archive ...
Archive: None
```

**`chmod` deletes the Synology ACL.** The path silently converts to "Linux
mode" and loses `has_ACL` / `is_inherit`. Two consequences measured
immediately after:

1. `chmod 2770` + `chown root:editors` still *happens* to let editors write —
   POSIX group rwx does the job — but everything created below it inherits
   nothing and lands **world-writable**, because DSM's sftp subsystem is
   configured `internal-sftp -f DAEMON -u 000` (umask 000):

   ```
   $ ls -lnR /volume1/CCSyncTest/posixtest
   -rw-rw-rw- 1 1030 65536 2 a_probe.txt
   drwxrwsrwx 1 1030 65536 0 a_probe_dir
   ```

2. `chmod 000` on an ACL'd directory locks *everyone* out, with no ACL left to
   save you: `A write ERR [Errno 13] Permission denied`.

The repair exists and works:

```
$ synoacltool -enforce-inherit /volume1/CCSyncTest/posixtest
$ synoacltool -get ...
Archive: is_inherit,is_support_ACL
	 [0] group:administrators:allow:rwxpdDaARWc--:fd-- (level:1)
	 [1] group:editors:allow:rwxpdDaARWc--:fd-- (level:1)
$ ls -land ...   ->  drwxrws---+ 1 0 65536 ...
```

The plan's literal command works too, on a path with no ACL at all:

```
$ synoacltool -add /volume1/CCSyncTest/addtest 'group:editors:allow:rwxpdDaARWc--:fd--'
	 [0] group:editors:allow:rwxpdDaARWc--:fd-- (level:0)
```

Syntax confirmed exactly as written in the plan. Note `synoacltool -add`
*re-establishes* `has_ACL` on a Linux-mode path, so `-add` is also a repair
tool, and `synoacltool -get-perm PATH USERNAME` is the read-only "what would
this user actually get" oracle (it prints `Final permission: [rwxpdDaARWc--]`)
— use it in `check_health.py`.

### VERDICT

**Group-write on Synology is pure ACE. Mode bits are decoration.** The plan's
"if it goes badly" fallback is the actual answer: *model group-write purely as
ACEs and drop the `chmod 2770` path on Synology*. Stronger than that —

- **`chmod` and `chown` must be forbidden anywhere under the tree share on the
  Synology backend.** Not "unnecessary": actively destructive. A single
  `chmod -R` inherited from the TrueNAS `setup_tree.py` code path would strip
  ACL inheritance off the whole project tree and leave new files 0666.
- `set_tree_acl()` does not need `synoacltool -add` at all if the share is
  created with `SYNO.Core.Share.Permission set` — that installs the
  `group:editors:allow:rwxpdDaARWc--:fd--` ACE at level 0 itself. Keep
  `-add` as the idempotent repair for shares created by hand, and
  `-enforce-inherit` as the "someone chmod'd it" fixer.
- `check_health.py`'s Synology arm should assert `synoacltool -get <tree>`
  contains `is_inherit` or `has_ACL` and *not* `It's Linux mode`.

**Changes:** WP3 step 2 (`backends/synology.py: set_tree_acl`), the
`setup_tree.py` chown/chmod lift in WP3 step 1, and mapping-table row
"Group-write perms".

---

## Spike 2 — pubkey SFTP for a nologin user, and exactly what gates it

### Baseline that works

```
$ synouser --get ccsync_a
User Shell  : [/sbin/nologin]
User Dir    : [/var/services/homes/ccsync_a]
$ grep '^ccsync_a:' /etc/passwd
ccsync_a:x:1030:100:CCSync Spike A:/var/services/homes/ccsync_a:/sbin/nologin
```

Key install (over SSH as the admin, exactly what WP2's paramiko helper will do):

```sh
mkdir -p /volume1/homes/ccsync_a/.ssh
printf '%s\n' 'ssh-ed25519 AAAA... ccsync_a' > /volume1/homes/ccsync_a/.ssh/authorized_keys
chown -R ccsync_a:users /volume1/homes/ccsync_a/.ssh
chmod 700 /volume1/homes/ccsync_a/.ssh
chmod 600 /volume1/homes/ccsync_a/.ssh/authorized_keys
```

Result — a `/sbin/nologin` user with a key gets SFTP with **no other change**:

```
ccsync_a: CONNECTED; cwd listing = ['arr-data', 'CCSyncTest', 'docker', 'home']
ccsync_b: CONNECTED; cwd listing = ['arr-data', 'CCSyncTest', 'docker', 'home']
```

**The SFTP root is the user's share view, not the filesystem.** The remote path
is `/CCSyncTest/Projects/...`, **not** `/volume1/CCSyncTest/...`. rclone
confirms:

```
$ rclone lsd :sftp:/ --sftp-host 192.168.0.104 --sftp-user ccsync_a --sftp-key-file <key> --sftp-shell-type none
          -1 2026-08-17 13:42:31        -1 CCSyncTest
          -1 2026-05-02 20:55:09        -1 arr-data
          -1 2026-08-17 13:45:48        -1 docker
          -1 2026-08-17 13:40:31        -1 home
```

Note the user's own home is `/home` (singular) in that view, and *other*
shares appear in the listing even without access — browsable ≠ readable.

### Toggles, one at a time

| Toggled | Result | sshd log line |
|---|---|---|
| **SFTP service off** (`SYNO.Core.FileServ.FTP.SFTP set enable=false`) | key auth **succeeds**, then `SSHException: Channel closed.` | `pam_unix(sshd:session): session opened for user ccsync_a` then `session closed` — no error |
| **`SYNO.SFTP` app privilege denied to group `editors`** | identical: `SSHException: Channel closed.` | identical, no error |
| home `chmod 777` | `AuthenticationException: Authentication failed.` | **nothing at all** |
| `.ssh` `chmod 777` | `AuthenticationException` | nothing |
| `authorized_keys` `chmod 666` | `AuthenticationException` | nothing |
| `authorized_keys` `chown root:root` | `AuthenticationException` | nothing |
| shell `/sbin/nologin` | **works** — SFTP is a subsystem, not a login shell | — |
| User Home service | already `enable: true`; `SYNO.Core.User.Home get` → `{"enable":true,"location":"/volume1",...}` | — |

Two findings that will cost someone a day if not written down:

1. **The SFTP service gate and the app-privilege gate are indistinguishable.**
   Both let key auth succeed and then close the subsystem channel. If an
   editor reports "rclone says channel closed", you must check *both*
   `SYNO.Core.FileServ.FTP.SFTP get` and
   `SYNO.Core.AppPriv.App allowed app_id=SYNO.SFTP`.
2. **StrictModes rejections are not logged.** DSM's sshd logs to
   `/var/log/auth.log` (not `messages`, and there is no `journalctl`), and at
   its default LogLevel it writes *no* line for `Authentication refused: bad
   ownership or modes`. A grep of the whole of `/var/log` for
   "Authentication refused" returned only echoes of my own `sudo` commands.
   The only signal is the client's `Authentication failed.`

The app privilege is called **`SYNO.SFTP`**, and it is a *separate* app id from
`SYNO.FTP`. It is `grant_by_default: true`, and the live rule set on this box
is the default one:

```
SYNO.Core.AppPriv.Rule list version=1 app_id=SYNO.SFTP
{"rules":[
  {"app_id":"SYNO.SFTP","entity_type":"everyone","entity_name":"everyone","allow_ip":["0.0.0.0"],"deny_ip":[]},
  {"app_id":"SYNO.SFTP","entity_type":"user","entity_name":"arr-user","allow_ip":[],"deny_ip":["0.0.0.0"]}]}
```

### VERDICT

**Yes — a nologin user SFTPs with a pubkey with zero extra grants**, provided
(a) the SFTP service is on, (b) nothing denies `SYNO.SFTP` for that user or a
group they are in, (c) `~`, `~/.ssh`, `~/.ssh/authorized_keys` satisfy sshd's
StrictModes and are owned by the user. DSM's default home mode `drwx--x--x+`
(711) already satisfies it — **do not chmod the home**, only `.ssh` and
`authorized_keys`.

Consequences for the plan:

- The mapping table's "grant the group the **FTP application privilege**" is
  **wrong on two counts**: the app id is `SYNO.SFTP`, and it is granted by
  default. `grant_sftp(group)` becomes a *verification* step, not a grant:
  read `AppPriv.Rule list app_id=SYNO.SFTP`, refuse loudly if an explicit deny
  covers `editors`. (`AppPriv.Rule set`/`delete` shapes are recorded in spike
  3 if a real grant is ever needed.)
- Enabling the **SFTP service** *is* required and *is* automatable — see
  spike 3. Add it to `grant_sftp` / `install` rather than to the manual
  prerequisites in WP7.
- `chmod` on `.ssh`/`authorized_keys` drops their Synology ACL (spike 1). That
  is fine and in fact desirable here — sshd only reads mode bits — but the
  home directory itself must keep its ACL. If someone chmods a home, repair
  with `synoacltool -enforce-inherit <home>` followed by
  `synoacltool -add <home> 'user:<u>:allow:rwxpdDaARWcCo:fd--'`, which
  reproduced DSM's own layout byte-for-byte against an untouched home.
- `fix_home_permissions()` on Synology = `chmod 700 ~/.ssh; chmod 600
  ~/.ssh/authorized_keys; chown -R <u>:users ~/.ssh` and *nothing else*.

---

## Spike 3 — DSM Core API shapes

This is the record WP2 codes from. Everything was exercised twice: over HTTPS
from the base rig with `requests` (`verify=False`) and, where the network path
refused, with `synowebapi --exec` on the box.

### 3.0 Discovery — the API manifests are on disk

Better than dev-tools capture: DSM ships the API definitions as JSON at
`/usr/syno/synoman/webapi/<API>.lib`. Reading them gives every method name and
version without guessing:

```sh
cat /usr/syno/synoman/webapi/SYNO.Core.User.lib     # also .Group .Share .AppPriv
```

Method inventory extracted from those files on this DSM:

| API | maxVersion | methods |
|---|---|---|
| `SYNO.Core.User` | 1 | list, get, set, delete, create, parse_user_list, import, import_status, import_stop, export_prepare(+_status,_stop), export, invite |
| `SYNO.Core.User.Group` | 1 | join, join_stop, join_list, join_status, get |
| `SYNO.Core.User.Home` | 1 | get, move_check, validate_set, set, status, stop |
| `SYNO.Core.User.PasswordConfirm` | 2 | auth |
| `SYNO.Core.User.PasswordPolicy` | 1 | get, set, check |
| `SYNO.Core.Group` | 1 | list, get, set, delete, create, admin_check, export… |
| `SYNO.Core.Group.Member` | 1 | list, add, remove, change, admin_check |
| `SYNO.Core.AppPriv` | 2 | list |
| `SYNO.Core.AppPriv.App` | 3 | preview(v2), allowed(v2), list(v2,v3) |
| `SYNO.Core.AppPriv.Rule` | 1 | get, set, delete, list |
| `SYNO.Core.Share` | 1 | create, set, list, get, delete, validate_delete, validate_set, restore, clone, move_status, stop_move, get_all_move_task |
| `SYNO.Core.Share.Permission` | 1 | list, list_by_user, list_by_group, set, set_by_user_group |
| `SYNO.Core.Share.Snapshot` | 2 | set_share_conf, get_share_conf, check_shareconf, set_schedule, get_schedule, create, list(v1,v2), delete, set |

`SYNO.API.Info query` (unauthenticated, `query.cgi`) agrees, and adds the
transport facts WP2 needs:

```
SYNO.API.Auth                  {"maxVersion": 7, "minVersion": 1, "path": "entry.cgi"}
SYNO.Core.User                 {"maxVersion": 1, "minVersion": 1, "path": "entry.cgi", "requestFormat": "JSON"}
SYNO.Core.Group                {"maxVersion": 1, ...}
SYNO.Core.Group.Member         {"maxVersion": 1, ...}
SYNO.Core.AppPriv              {"maxVersion": 2, ...}
SYNO.Core.AppPriv.App          {"maxVersion": 3, ...}
SYNO.Core.AppPriv.Rule         {"maxVersion": 1, ...}
SYNO.Core.Share                {"maxVersion": 1, ...}
SYNO.Core.Share.Permission     {"maxVersion": 1, ...}
SYNO.Core.Share.Snapshot       {"maxVersion": 2, ...}
SYNO.Core.FileServ.FTP.SFTP    {"maxVersion": 1, ...}
SYNO.Core.User.Home            {"maxVersion": 1, ...}
SYNO.Docker.Project            {"maxVersion": 1, ...}
```

### 3.1 THE gotcha: `SYNO.API.Auth` **version 7**, not 6

Logging in at version 6 gets you a working sid that can `list` and `get` and is
**refused on every mutation** with error 105 and the response header
`x-request-error: noprivilege`:

```
POST /webapi/entry.cgi  api=SYNO.Core.User method=set version=1 name=ccsync_a description=...
-> {"error":{"code":105},"success":false}      x-request-error: noprivilege
```

Same request, same account, same everything, after logging in with
`version=7`:

```
-> {"data":{"name":"ccsync_a","password_last_change":20682,"uid":1030},"success":true}
```

This was tested across `session=DSM|ccsync` × `version=3|6|7` and the login
version is the only variable that matters. Adding `SynoToken`, an
`X-SYNO-CONFIRM-PW-TOKEN`, `Referer`/`Origin`, port 5000 vs 5001 — none of it
moves error 105 at version 6.

Working login:

```
GET https://<nas>:5001/webapi/auth.cgi
    ?api=SYNO.API.Auth&method=login&version=7
    &account=<user>&passwd=<pw>&session=DSM&format=sid&enable_syno_token=yes

{"data":{"account":"Cablewrap",
         "device_id":"63Leh5_...",
         "ik_message":"",
         "is_portal_port":false,
         "sid":"MHhkYf2Dm4EX...",
         "synotoken":"ybn6DQI7qejJ2"},
 "success":true}
```

The account has 2FA off. `format=sid` returns the sid in the body; requests
then carry `_sid=<sid>` plus `SynoToken=<synotoken>` (also sent as the
`X-SYNO-TOKEN` header).

DSM 7's password-reconfirmation token is real and obtainable, but was **not
required** for any call below once login v7 was used:

```
POST entry.cgi api=SYNO.Core.User.PasswordConfirm method=auth version=2 password=<pw>
{"data":{"SynoConfirmPWToken":"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...."},"success":true}
```

(JWT, `aud=confirm-password-token`, 300 s TTL. Worth implementing behind a
retry-on-105 in case another DSM build demands it.)

### 3.2 Booleans must be JSON literals — error 3103

`SYNO.Core.User create` with Python `False` (rendered `"False"` by `requests`)
fails with 3103; the same call with `"false"` succeeds. Bisected one parameter
at a time:

```
name                     -> {'data': {'name': 'ccsync_probe', 'uid': 1033}, 'success': True}
+password                -> success
+description             -> success
+email                   -> success
+expired                 -> success
+cannot_chg_passwd="false"-> success
+password_never_expire="true" -> success
+notify_by_email="false" -> success
+send_password="false"   -> success
```

Every boolean/array parameter must be serialised as JSON (`json.dumps`), never
as a Python repr. WP2's client should have a single `_param()` that enforces
this — it is the difference between a working provisioner and an opaque 3103.

### 3.3 Recorded request/response shapes

**Users**

```
GET  entry.cgi api=SYNO.Core.User method=list version=1
     type=local offset=0 limit=50 additional=["email","description","expired","uid"]
{"data":{"offset":0,"total":6,"users":[
   {"description":"CCSync Spike A","email":"","expired":"normal","name":"ccsync_a","uid":1030}, ...]},
 "success":true}

GET  ... method=get version=1 name=ccsync_a additional=["email","description","expired"]
{"data":{"users":[{"description":"CCSync Spike A","email":"","expired":"normal","name":"ccsync_a","uid":1030}]},"success":true}
     # note: `get` returns a LIST under "users", not an object. 3106 = no such user.

POST ... method=create version=1
     name=ccsync_b password=<pw> description="CCSync Spike B" email=""
     expired=normal cannot_chg_passwd=false password_never_expire=true
     notify_by_email=false send_password=false
{"data":{"name":"ccsync_b","uid":1031},"success":true}

POST ... method=set version=1 name=ccsync_a description="..."            # and/or password=<pw>
{"data":{"name":"ccsync_a","password_last_change":20682,"uid":1030},"success":true}

POST ... method=delete version=1 name=["ccsync_probe"]                   # JSON ARRAY
{"data":{"errors":[3102]},"success":true}     # 3102 appears even on a successful delete
     # name as a plain string -> {"error":{"code":3101}}
```

The identical call is available on the box, which is what a pure-SSH fallback
would use, and it prints its own parsed parameter dict:

```
$ synowebapi --exec api=SYNO.Core.User method=create version=1 name=ccsync_b \
      password='<pw>' description='CCSync Spike B' email='' expired=normal \
      cannot_chg_passwd=false password_never_expire=true notify_by_email=false send_password=false
[Line 295] Exec WebAPI: api=SYNO.Core.User, version=1, method=create,
   param={"cannot_chg_passwd":false,...,"name":"ccsync_b",...}, runner=SYSTEM_ADMIN
{"data":{"name":"ccsync_b","uid":1031},"httpd_restart":false,"success":true}
```

`synowebapi` runs as `runner=SYSTEM_ADMIN` and is **not** subject to the
version-6 privilege problem. Its `[Line 265] Not a json value: <x>` lines are
noise, not errors — it is telling you it treated a bare token as a string.

Error codes seen: **105** no privilege (see 3.1), **103** no such method,
**3101** bad delete argument, **3102** in `errors[]` on delete, **3103**
invalid parameter (bad boolean), **3106** no such user, **3107** user already
exists, **3206** group already exists, **3400** bad/missing params on
`AppPriv.Rule`, **403** feature not installed (see spike 8), **119** no sid.

**Groups**

```
POST entry.cgi api=SYNO.Core.Group method=create version=1 name=editors
{"data":{"gid":65536,"name":"editors"},"success":true}         # 3206 if it exists

GET  ... api=SYNO.Core.Group method=list version=1 type=local offset=0 limit=50
{"data":{"groups":[{"description":"","name":"administrators"},{"description":"","name":"editors"},...],
         "offset":0,"total":4},"success":true}

POST ... api=SYNO.Core.Group method=delete version=1 name=["ccsync_probe_grp"]
{"data":{},"success":true}
```

**Group membership — the silent-no-op trap.** `SYNO.Core.Group.Member add`
returns `{"data":{},"success":true}` *whatever you send it*. The parameter it
actually reads is `name` (a JSON array); `members` is ignored:

```
members=["ccsync_a"]  -> {"data":{},"success":true}   members afterwards: []      <-- did nothing
name=["ccsync_a"]     -> {"data":{},"success":true}   members afterwards: [ccsync_a]
```

Working shape, and the read-back that must always follow it:

```
POST entry.cgi api=SYNO.Core.Group.Member method=add version=1
     group=editors name=["ccsync_a","ccsync_b"]
{"data":{},"success":true}

GET  ... method=list version=1 group=editors offset=0 limit=50
{"data":{"offset":0,"total":2,"users":[
   {"description":"CCSync Spike A","name":"ccsync_a","uid":1030},
   {"description":"CCSync Spike B","name":"ccsync_b","uid":1031}]},"success":true}
```

The alternative, user-side and asynchronous:

```
GET  api=SYNO.Core.User.Group method=get  version=1 name=ccsync_a
{"data":{"groups":["editors","users"]},"success":true}
POST api=SYNO.Core.User.Group method=join version=1 name=ccsync_a join_group=["editors"]
{"data":{"task_id":"@administrators/groupbatch1786945137B0F58ABA"},"success":true}   # poll join_status
```

For WP2, `SYNO.Core.User.Group get` is the cleanest `is_editor()`: one call,
synchronous, returns the group list for a user.

**App privileges**

```
GET api=SYNO.Core.AppPriv.App method=list version=3
{"data":{"applications":[
  {"app_id":"SYNO.AFP","grant_by_default":true,"grant_type":["local","domain","ldap"],
   "isInternal":true,"name":"AFP","service_type":"modules/LegacyApps","supportIP":true},
  {"app_id":"SYNO.Desktop",...,"name":"DSM"},
  {"app_id":"SYNO.FTP",...,"name":"FTP"},
  {"app_id":"SYNO.Rsync",...},
  {"app_id":"SYNO.SFTP",...,"name":"SFTP"}, ...]},"success":true}

GET api=SYNO.Core.AppPriv.App method=allowed version=2 app_id=SYNO.SFTP
{"data":{"offset":0,"total":5,"users":[{"name":"admin"},{"name":"Cablewrap"},
   {"name":"ccsync_a"},{"name":"ccsync_b"},{"name":"vruskinfox"}]},"success":true}

GET api=SYNO.Core.AppPriv.Rule method=list version=1 app_id=SYNO.SFTP
{"data":{"rules":[{"allow_ip":["0.0.0.0"],"app_id":"SYNO.SFTP","deny_ip":[],
                   "entity_name":"everyone","entity_type":"everyone"},
                  {"allow_ip":[],"app_id":"SYNO.SFTP","deny_ip":["0.0.0.0"],
                   "entity_name":"arr-user","entity_type":"user"}]},"success":true}

POST api=SYNO.Core.AppPriv.Rule method=set version=1 app_id=SYNO.SFTP
     rules=[{"app_id":"SYNO.SFTP","entity_type":"group","entity_name":"editors",
             "allow_ip":["0.0.0.0"],"deny_ip":[]}]
{"success":true}

POST api=SYNO.Core.AppPriv.Rule method=delete version=1 app_id=SYNO.SFTP
     rules=[{"app_id":"SYNO.SFTP","entity_type":"group","entity_name":"editors"}]
{"success":true}
```

`SYNO.Core.AppPriv.Rule get` returns 3400 for every parameter combination
tried (`app_id`, `appPrivId`, `app_id`+`member_type`+`member_name`) — **use
`list` and filter client-side**. `SYNO.Core.AppPriv list version=2` also
returns 3400; its parameters were not determined and it is not needed.

**Shares**

```
POST entry.cgi api=SYNO.Core.Share method=create version=1
     name=CCSyncTest
     shareinfo={"name":"CCSyncTest","vol_path":"/volume1","desc":"CC Sync port spike",
                "enable_share_cow":true,"enable_recycle_bin":false,"hidden":false,
                "enable_share_compress":false}
{"data":{"name":"CCSyncTest"},"success":true}

GET  ... method=get version=1 name=arr-data additional=["hidden","encryption","is_aclmode",
        "unite_permission","is_support_acl","recyclebin","support_snapshot","enable_share_cow",...]
{"data":{"name":"arr-data","vol_path":"/volume1","uuid":"028bf73b-...","is_aclmode":true,
         "is_support_acl":true,"support_snapshot":true,"support_action":511,...},"success":true}

GET  ... method=list version=1 shareType=all additional=[...]     # same fields, array under "shares"

POST api=SYNO.Core.Share.Permission method=set version=1
     name=CCSyncTest user_group_type=local_group
     permissions=[{"name":"editors","is_readonly":false,"is_writable":true,
                   "is_deny":false,"is_custom":false}]
{"success":true}

GET  api=SYNO.Core.Share.Permission method=list version=1
     name=CCSyncTest user_group_type=local_group offset=0 limit=50
{"data":{"items":[{"is_admin":true,...,"is_writable":true,"name":"administrators"},
                  {"is_admin":false,...,"is_writable":true,"name":"editors"},
                  {"is_admin":false,...,"is_writable":false,"name":"http"},
                  {"is_admin":false,...,"is_writable":false,"name":"users"}],"total":4},"success":true}
```

CLI equivalent for the SSH fallback (`synoshare --help` shape confirmed on the box):

```
synoshare --add <name> <desc> <path> <na> <rw> <ro> <browsable{0|1}> <adv_privilege{0~7}>
synoshare --setuser <name> {NA|RO|RW} {+|-|=} <comma,list>
synoshare --get <name>          # dumps Path / RW list / ACL / WinShare / FTPPrivilege / Status
```

**Home service, SFTP service**

```
GET  api=SYNO.Core.User.Home method=get version=1
{"data":{"enable":true,"enable_domain":false,"enable_ldap":false,"enable_recycle_bin":true,
         "encryption":0,"location":"/volume1","remote_location":"","userhome_in_s2s":false},"success":true}
     # -> homes live at <location>/homes/<user>, symlinked as /var/services/homes/<user>

GET  api=SYNO.Core.FileServ.FTP.SFTP method=get version=1
{"data":{"enable":false,"portnum":22},"success":true}
POST api=SYNO.Core.FileServ.FTP.SFTP method=set version=1 enable=true portnum=22
{"success":true}
GET  ... method=get version=1
{"data":{"enable":true,"portnum":22},"success":true}      # takes effect in <6 s, no restart
```

**Container Manager (read-only)**

```
$ synowebapi --exec api=SYNO.Docker.Project method=list version=1
{"data":{ "<uuid>": {"containerIds":[...],"created_at":"2026-01-24T06:08:20Z",
    "id":"<uuid>","is_package":false,"name":"qbittorrent","path":"/volume1/docker/qbittorrent",
    "share_path":"/docker/qbittorrent","status":"RUNNING","version":2,
    "enable_service_portal":false,"service_portal_port":0,...}, ... }}
```

Keyed by uuid, not an array. See spike 5 for what it does *not* contain.

### VERDICT

**The DSM Core API is usable and pinnable — go with plan decision 2, with two
corrections.** (a) `SYNO.API.Auth` **version 7**; anything lower is read-only
for an administrators-group service account. (b) Every parameter is JSON, and
`Group.Member add` must be verified by read-back because it lies.

WP2 changes:
- Version-gate on `SYNO.API.Info` exactly as planned, and additionally record
  the login version — a DSM that only offers Auth ≤ 6 must fall back to SSH
  provisioning rather than silently 105 on the first editor create.
- Add `SYNO.Core.User.PasswordConfirm auth v2` behind a retry-on-105.
- The 3103-on-Python-bool trap justifies a single serialising helper and a
  `fake_synology.py` that rejects `"True"`/`"False"` the same way DSM does.
- Reading `/usr/syno/synoman/webapi/*.lib` over SSH is a cheap, exact shape
  check for the "refuse to guess" discipline — better than probing.
- Timing: WP2's estimate holds. The "add ~3 days for an all-SSH path" risk
  does **not** need to fire; but note `synowebapi --exec` gives the identical
  API over SSH with SYSTEM_ADMIN rights, so the fallback is nearly free if a
  future DSM tightens the network path.

---

## Spike 4 — Tailscale serve

```
$ /var/packages/Tailscale/target/bin/tailscale version
1.58.2

$ docker run -d --rm --name ccsync-spike-web -p 127.0.0.1:8480:80 nginx:alpine
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8480/
200
```

1.58's syntax (from `tailscale serve --help` on the box) is
`serve <target>` with `--bg`, `--https uint`, `--yes`:

```
$ tailscale serve --bg --yes --https=443 http://127.0.0.1:8480
Serve is not enabled on your tailnet.
To enable, visit:

         https://login.tailscale.com/f/serve?node=n6YZ9Q2NQx11CNTRL

$ tailscale serve status
No serve config
```

**Serve is gated at the tailnet level, not the node.** It needs a one-time
click in the Tailscale admin console (which also turns on HTTPS certificates
for the whole tailnet). This was *not* done — it is an account-wide change
affecting the customer's other machines and requires an interactive browser
login. So `tailscale serve` itself is **untested on this box**; what is proven
is that 1.58.2 supports it, the flags are as above, and the tailnet must be
opted in first.

Corroborating: `tailscale status --json` on the NAS reports
`"CertDomains": null` — no cert domains provisioned, consistent with HTTPS
being off tailnet-wide.

What *does* work, measured:

```
Self: HostName=Cablewrap-1  DNSName=nas.tail26290e.ts.net.
      TailscaleIPs=[100.65.15.123, fd7a:115c:a1e0::c901:f7b]
      TUN=True  BackendState=Running  MagicDNSSuffix=tail26290e.ts.net
```

Inbound over the tailnet works, and the path to the base rig is **direct, not
DERP**:

```
$ tailscale ping 100.65.15.123          # from the base rig (100.74.115.96)
pong from nas (100.65.15.123) via 192.168.0.104:41641 in 2ms
```

(`tailscale status --json` on the NAS shows the peer with `"Relay":"hkg"` and
`"CurAddr":""` only while idle; once traffic flows the ping resolves to the
direct LAN endpoint. Both machines are on the same LAN here, so this does not
prove NAT traversal for a remote editor.)

DSM services answer over the tailnet address and over MagicDNS:

```
GET https://100.65.15.123:5001/webapi/query.cgi?... -> 200 (509 ms first call)
GET https://nas.tail26290e.ts.net:5001/webapi/...   -> 200
GET https://nas.tail26290e.ts.net/                  -> 403   <-- DSM's own nginx, not serve
```

That last line is the sting: **DSM's nginx already owns `0.0.0.0:443` and
`0.0.0.0:5001`** (`netstat -tlnp` → `12150/nginx: master` on 80, 443, 5000,
5001, 1337, 5357). Any plan that says "publish the dashboard on :443" has to
go through `tailscale serve` (which terminates inside tailscaled) or pick
another port; it cannot bind 443 itself.

`tailscale configure-host` was not needed: the package is already running with
`TUN: true` and advertising routes (`"AdvertiseRoutes":["192.168.0.0/24",
"0.0.0.0/0","::/0"]`), i.e. not in userspace mode on this unit.

### VERDICT

**Plan decision 5 survives but gains a prerequisite and a fallback.**

- Bind `127.0.0.1:8480` — confirmed correct and confirmed enforceable (spike 5).
- `tailscale serve --bg --https=443 http://127.0.0.1:8480` is the right 1.58+
  command, **plus `--yes`** for non-interactive installs (without it the
  command blocks on a prompt; this cost a 2-minute timeout during the spike).
- **New WP4 requirement:** "Serve/HTTPS enabled for the tailnet" is a
  customer prerequisite with a one-time admin-console click. The installer
  must detect the `Serve is not enabled on your tailnet` string and stop with
  that URL rather than reporting success. Add it to WP7's published
  requirements.
- **New WP4 constraint:** DSM's nginx holds :443/:5001. Document that the
  dashboard is reached at `https://<host>.<tailnet>.ts.net/` **only** via
  serve, and that the DSM-reverse-proxy fallback means sharing that nginx.
- The userspace-mode worry in the plan ("no tailnet interface IP for compose
  to bind") did not materialise on a unit with `TUN: true`, but binding
  loopback + serve is the right design either way because it works in both
  modes.

---

## Spike 5 — `docker compose` from SSH

```
$ mkdir -p /volume1/docker/ccsync-spike
$ cat /volume1/docker/ccsync-spike/compose.yaml
services:
  sleeper:
    image: alpine:3.19
    container_name: ccsync-spike-sleeper
    command: ["sleep", "3600"]
    restart: unless-stopped
    ports:
      - "127.0.0.1:8384:8384"

$ cd /volume1/docker/ccsync-spike && docker compose -p ccsync-spike up -d
 Network ccsync-spike_default  Created
 Container ccsync-spike-sleeper  Started

$ docker compose ls
NAME                 STATUS              CONFIG FILES
arr-apps             running(3)          /volume1/docker/arr-apps/docker-compose.yml
ccsync-spike         running(1)          /volume1/docker/ccsync-spike/compose.yaml
...
$ docker ps --filter name=ccsync
ccsync-spike-sleeper|alpine:3.19|Up|127.0.0.1:8384->8384/tcp

$ netstat -tlnp | grep 8384
tcp  0  0 127.0.0.1:8384   0.0.0.0:*   LISTEN   17201/docker-proxy

$ docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' ccsync-spike-sleeper
unless-stopped
```

Loopback binding is honoured exactly — `docker-proxy` listens on
`127.0.0.1:8384` only, nothing on `0.0.0.0`. Compose labels are the standard
v2 ones (`com.docker.compose.project=ccsync-spike`,
`...project.config_files=/volume1/docker/ccsync-spike/compose.yaml`,
`com.docker.compose.version=2.20.1`), so `docker compose ls`, `restart`,
`down` all work from any directory with `-p` + `-f`.

Container Manager, however, does **not** adopt it:

```
$ synowebapi --exec api=SYNO.Docker.Project method=list version=1 | grep -c ccsync-spike
0
```

It shows up under Container Manager's *Container* list (it is a container) but
not as a *Project*. Every pre-existing project on this box
(`qbittorrent`, `bazarr`, `arr-apps`, …) **is** registered, which means those
were created through the UI, so this spike does not prove that a
CLI-created stack behaves identically to a UI project in every respect.

**Reboot survival could not be tested** — the box is a live production NAS
that must not be rebooted, uptime 77 days. What can be said: the daemon-level
mechanism (`restart: unless-stopped` + dockerd starting with the Container
Manager package) is the same one the box's other containers rely on, and
several have `Up 2 months` against a 77-day uptime, i.e. they have been
restarted by the daemon rather than by a person. That is suggestive, not
proof. **WP6 must reboot a test unit and re-check.**

### VERDICT

**Plan decision 4 is confirmed as written**, including its stated caveat.
`docker compose up -d` over SSH coexists with Container Manager, binds
loopback, and is fully manageable by `docker compose ls / restart / down`.
The "if it goes badly" fallback (register the stack as a Container Manager
project via `synowebapi`) is **not needed**, but keep it in the back pocket
against the reboot question, which is unanswered.

WP3 notes:
- `stack_installed()` = `docker compose ls --format json` filtered on
  `Name == "ccsync"` — reliable and cheap.
- Host-root safety regex `^/volume\d+/[^/]+/ccsync(/…)*$` is right; the
  project directory `/volume1/docker/ccsync` matches the convention every
  existing stack on this box already follows.
- Container names will be `ccsync-dashboard-1` etc. as the plan says (compose
  v2 naming with `-p ccsync`), confirmed by
  `ccsync-spike-sleeper` only because `container_name:` was set explicitly;
  without it the name would have been `ccsync-spike-sleeper-1`.
- **Do not write compose files through `sh -c '...'` heredocs over SSH** —
  quoting eats them. Base64 the payload (or SFTP it), which is what the
  existing deploy engine already does.

---

## Spike 6 — SFTP vs SMB throughput, and a defect in the shipped tuning

Base rig → NAS, 1 GbE LAN, 2 GiB single file, rclone v1.74.4.
The NAS was **not idle** (jellyfin was transcoding at ~145 % CPU throughout),
and `/volume1` is 100 % full with ~60 GB free — both make these numbers
conservative.

| Direction | Protocol | Flags | Throughput |
|---|---|---|---|
| Up (base rig → NAS) | SFTP | companion tuning: `--sftp-chunk-size 255Ki --sftp-concurrency 64 --sftp-connections 16 --transfers 4 --checkers 16 --ignore-checksum` | **90.2 MiB/s** |
| Up | SFTP | `--sftp-chunk-size 64Ki` (rest same) | 92.6 MiB/s |
| Up | SFTP | rclone defaults (32Ki) | 93.5 MiB/s |
| Down | SFTP | companion tuning (255Ki) | **FAILS — truncates at 539,000,832 bytes** |
| Down | SFTP | rclone defaults (32Ki) | **112.2 MiB/s** |
| Down | SFTP | `--sftp-chunk-size 64Ki` | 112.2 MiB/s |
| Up | SMB | `--smb-host/-user/-pass`, same transfers/checkers | **102.2–104.2 MiB/s** |
| Down | SMB | same | **112.0 MiB/s** |

### The defect

```
$ rclone copy :sftp:/CCSyncTest/bench/bench2g.bin ./down --sftp-chunk-size 255Ki ... --retries 1
ERROR : corrupted on transfer: sizes differ
        src(sftp://ccsync_a@192.168.0.104:22//CCSyncTest/bench/bench2g.bin) 2147483648
        vs dst(...) 539000832
```

Deterministic, same byte count every attempt. Bisected:

```
chunk=32Ki   got=2147483648   OK
chunk=64Ki   got=2147483648   OK
chunk=128Ki  got=0            FAIL
chunk=200Ki  got=0            FAIL
chunk=240Ki  got=0            FAIL
chunk=248Ki  got=0            FAIL
chunk=252Ki  got=0            FAIL
chunk=255Ki  got=0            FAIL
```

Cause, confirmed on the box:

```
$ ssh -V
OpenSSH_8.2p1, OpenSSL 1.1.1u  30 May 2023
$ strings /usr/bin/sshd | grep -i 'limits@openssh'
(nothing)
```

The `limits@openssh.com` SFTP extension — which is how a client learns it may
issue reads larger than 64 KiB — landed in **OpenSSH 8.5**. DSM 7.2.1 ships
**8.2p1**, so its sftp-server caps read replies at 64 KiB. rclone asks for
255 KiB, gets a short reply, and its concurrent-read path treats the short
read as end-of-file. Uploads are unaffected because writes are sent, not
requested. TrueNAS SCALE ships OpenSSH 9.x, which is exactly why nobody has
ever seen this.

Note the failure is **silent-ish**: rclone reports it as
`corrupted on transfer: sizes differ` and deletes the partial, so no corrupt
file is left behind — but every lane-B pass would fail every large file,
forever, with an error that reads like a network fault.

### CPU

`top` on the NAS during the SFTP upload:

```
1119 root      sshd: ccsync_a@n+   40.0 %CPU
1120 ccsync_a  sshd: ccsync_a@i+   15.0 %CPU
```

~0.55 of one J4125 core to sustain 90 MiB/s of SFTP, i.e. ~1.7 cores' worth at
2.5 GbE line rate on a 4-core part. SMB's smbd did not surface in the sampled
`top` window, so a like-for-like CPU comparison was **not** obtained; the
throughput gap (SMB ~12 % faster) is the only evidence either way.

### VERDICT

**SFTP does not "win" on this unit — it loses by ~12 % on upload and ties on
download — but at 1 GbE everything is at line rate, so the protocol choice is
not the bottleneck and lanes A/B do not need to change.** The plan's fallback
("promote SMB for lane A/B on Synology") is **not** triggered on throughput
grounds. Revisit only on a ≥2.5 GbE unit, where the per-stream single-core
cost of SSH will bite first.

But two things must change:

1. **`sftp_chunk_size` must be capped at 64Ki on Synology backends** (or on
   any server advertising OpenSSH < 8.5). This is not a WP5 nicety, it is a
   correctness fix: at 255Ki, lane B cannot download anything larger than
   ~514 MiB from a DSM 7.2 box. The knob already exists and is per-key
   overridable (`companion/src/ccsync_companion/config.py`
   `"sftp_chunk_size"`, consumed by `sync/rclone_lane.py`
   `DEFAULT_SFTP_CHUNK_SIZE`), so the fix is a site-manifest value, not code —
   but the *default* for a Synology site must be 64Ki.
2. The WAN rationale for 255Ki still stands and is worth preserving
   **asymmetrically**: lane A (upload) may keep 255Ki, lane B (download) must
   not exceed 64Ki. They are separate rclone invocations, so this is
   expressible. At 64Ki × 64 the download window is 4 MiB → ~27 MB/s at
   150 ms RTT, still double rclone's stock 2 MiB window, so the regression
   versus TrueNAS is real but bounded. Say so in `SERVER-SYNOLOGY.md`.

Also worth carrying into the code: `--sftp-shell-type none` is required for
DSM editors. Their shell is `/sbin/nologin`, so rclone's `shell_type = unix`
(set today in `rclone.conf` for the TrueNAS site) cannot run `md5sum` over
SSH. The manifest needs a `shell_type` field alongside `port`.

---

## Spike 7 — uid/gid

```
$ id ccsync_a
uid=1030(ccsync_a) gid=100(users) groups=100(users),65536(editors)
$ id ccsync_b
uid=1031(ccsync_b) gid=100(users) groups=100(users),65536(editors)
$ grep -E '^(editors|users|administrators|http):' /etc/group
administrators:x:101:admin,Cablewrap
editors:x:65536:ccsync_a,ccsync_b
http:x:1023:
users:x:100:
```

DSM's allocation policy, read off this box:

- **Local users start at 1024** and increment: `admin`=1024, `guest`=1025,
  `Cablewrap`=1026, `vruskinfox`=1028, `arr-user`=1029, then ours at 1030/1031.
  Deleted uids are **not** reused — creating and deleting nine probe accounts
  during spike 3 burned uids 1032–1041, and the next create would be 1042.
- **Local groups start at 65536.** `editors` got **gid 65536** — not 3001, not
  1026. Built-ins are below that (`users`=100, `administrators`=101,
  `http`=1023).
- **Package users/groups live in the 170000–300000 range**
  (`PlexMediaServer`=297536, `StorageAnalyzer`=276949, `sc-jellyfin`=187774
  with primary gid 207066 = `synocommunity`). Never collide with these.
- Every local user's **primary gid is 100 (`users`)**; `synouser --add` gives
  no way to set it. Group membership is supplementary only. This is fine for
  the ACL model (spike 1) but it means `chown :editors` is the *only* way to
  put `editors` in a file's group — and `chown` is banned under the tree.

Bind-mount identity passes straight through, unmapped, and the ACL applies to
container processes:

```
$ docker run --rm -u 1030:65536 -v /volume1/CCSyncTest:/data alpine:3.19 \
      sh -c 'id; touch /data/uidtest.txt && echo CONTAINER-WRITE-OK; ls -ln /data/uidtest.txt'
uid=1030 gid=65536 groups=65536
CONTAINER-WRITE-OK
-rwxrwxrwx    1 1030     65536            0 /data/uidtest.txt      # container's view

$ ls -ln /volume1/CCSyncTest/uidtest.txt                            # host's view
-rwxrwx---+ 1 1030 65536 0
$ synoacltool -get /volume1/CCSyncTest/uidtest.txt
Owner: [ccsync_a(user)]
	 [0] group:administrators:allow:rwxpdDaARWc--:---- (level:1)
	 [1] group:editors:allow:rwxpdDaARWc--:---- (level:1)
```

Note the container sees mode `777` where the host sees `770` — the mode-bit
projection differs across the ACL layer, so **no container may make an access
decision from mode bits on a bind-mounted share path**.

A container running as root writes files owned `0:0` with mode `0000` and only
inherited ACEs — which is exactly the "b-roll indexer wrote files nobody can
edit" failure the TrueNAS side already learned. `user:` must be set on every
service that touches the tree.

**"Do bind-mounted dirs keep uid/gid across DSM updates?" was not answered** —
no DSM update was pending on this box and one must not be forced on a
production NAS. What is now known is the *risk shape*: uids are stable
identifiers stored in `/etc/passwd`, and package uids move around in the
170k–300k range, so the danger is a *new package* claiming a uid, not an update
renumbering ours. WP6 must confirm across a real minor update.

### VERDICT

**Plan decision "read the uid/gid at install time and template
`${APP_UID}:${APP_GID}`" is confirmed and is mandatory.** A hardcoded
`user: "3000:3001"` would be wrong on every DSM box; on this one the correct
values would be `1030:65536`-shaped. Also:

- `create_or_update_editor` must refuse uid < 1024 (not 1026 as the plan says
  — `admin` is 1024 and `guest` 1025 on this box).
- Add a "never touch uid ≥ 170000" rule for package accounts.
- Record `editors`' gid from `SYNO.Core.Group create`'s response
  (`{"data":{"gid":65536,...}}`) — it is returned directly, no `id` call
  needed.

---

## Spike 8 — Btrfs snapshots without the Snapshot Replication package

```
$ synopkg list --name | grep -i -E 'snapshot|replic'
(nothing)
$ ls /volume1/@appstore
CloudSync ContainerManager DownloadStation MailServer Node.js_* PHP* Perl
PlexMediaServer StorageAnalyzer SynologyApplicationService SynologyPhotos
Tailscale TextEditor UniversalViewer WebStation exFAT-Free ffmpeg7 jellyfin
r8152 synocli-videodriver
```

Not installed. Nonetheless:

**`synobtrfssnap` is part of base DSM** (`/usr/syno/bin`), and its usage is:

```
-c --create-subvol <SUBVOL_PATH>
-d --delete-subvol <SUBVOL_PATH>
-t --take-snapshot -s <SRC_PATH> -d <DST_PATH> [-r]
-l --list-subvol <VOL_PATH> [-f PATH] [-a] [-r] [-s] [-d]
-g --get-count <VOL_PATH>  /  -G --get-global-count  /  -C --check-global-count
-m --mark-deleted-subvol   /  -D --clean-deleted-subvol
-u --cal-exclusive-usage <SUBVOL_PATH>...
```

**Shares are Btrfs subvolumes**, so plain `btrfs` works too:

```
$ btrfs subvolume list /volume1 | grep -i ccsync
ID 1654 gen 9596744 top level 256 path CCSyncTest
```

**And `SYNO.Core.Share.Snapshot` create/list/delete work without the package:**

```
$ synowebapi --exec api=SYNO.Core.Share.Snapshot method=create version=1 \
      name=CCSyncTest desc='ccsync spike'
{"data":"GMT+08-2026.08.17-14.00.36","httpd_restart":false,"success":true}

$ synowebapi --exec api=SYNO.Core.Share.Snapshot method=list version=2 name=CCSyncTest
{"data":{"snapshots":[{"time":"GMT+08-2026.08.17-14.00.36"}],"total":1},"success":true}
```

The snapshot lands at `/volume1/@sharesnap/<share>/<GMT±TZ-YYYY.MM.DD-HH.MM.SS>`,
as a genuine read-only Btrfs subvolume, with a sidecar metadata file:

```
$ btrfs subvolume show /volume1/@sharesnap/CCSyncTest/GMT+08-2026.08.17-14.00.36
	UUID: 99f91510-...   Parent UUID: 76ff695b-...
	Subvolume ID: 1670   Flags: readonly

$ cat /volume1/@sharesnap/@CCSyncTest.meta
[GMT+08-2026.08.17-14.00.36]
hide=false
take-by=synowebapi
uuid=99f91510-3cb6-eb4d-b260-6bd41cf6642c
lock=true
worm_lock=false
desc=
snap_size=40960
```

### Restore drill, done

```
$ echo 'PRECIOUS v1' > /volume1/CCSyncTest/Projects/demo/sub/precious.txt
$ synowebapi ... Share.Snapshot create ...
$ rm -rf /volume1/CCSyncTest/Projects/demo          # destroy
$ ls /volume1/CCSyncTest/Projects/
(empty)
$ mkdir -p /volume1/CCSyncTest/Projects/demo/sub
$ cp -a /volume1/@sharesnap/CCSyncTest/GMT+08-2026.08.17-14.00.36/Projects/demo/sub/precious.txt \
        /volume1/CCSyncTest/Projects/demo/sub/
$ cat /volume1/CCSyncTest/Projects/demo/sub/precious.txt
PRECIOUS v1
```

Single-file restore is a plain `cp` out of a normal directory tree. **But**:

```
$ ls -ln /volume1/CCSyncTest/Projects/demo/sub/precious.txt
----------+ 1 0 0 12 precious.txt        # owner root, not the original ccsync_a
$ synoacltool -get .../precious.txt
Owner: [root(user)]
```

`cp -a` does not carry the Synology ACL or ownership; the restored file
re-inherits from its destination. That is *safe* (editors still have access
via the inherited ACE) but the owner changes. Use `synoacltool -copy
PATH_SRC PATH_DST` if owner fidelity matters.

### What the package IS needed for

```
$ synowebapi --exec api=SYNO.Core.Share.Snapshot method=get_share_conf version=1 name=CCSyncTest
{"error":{"code":403},"success":false}

POST api=SYNO.Core.Share.Snapshot method=set_schedule version=1 name=CCSyncTest
     enable_snapshot_schedule=true schedule={"hour":3,"min":0,"repeat":1001,...}
{"error":{"code":403},"success":false}

GET  ... method=get_schedule version=1 name=CCSyncTest
{"data":{"enable_snapshot_schedule":false,"schedule":{...},"task_id":-1},"success":true}
```

So: **taking, listing and deleting snapshots is free; scheduling and retention
policy require Snapshot Replication** (error 403 = feature/package absent —
the same code `get_share_conf` returns).

Manual snapshots made outside the API are invisible to it:

```
$ btrfs subvolume snapshot -r /volume1/CCSyncTest /volume1/@sharesnap/CCSyncTest/ccsync-manual-test
Create a readonly snapshot of '/volume1/CCSyncTest' in '.../ccsync-manual-test'   (Flags: readonly)
$ synobtrfssnap -t -s /volume1/CCSyncTest -d /volume1/@sharesnap/CCSyncTest/ccsync-manual-test2 -r
$ synowebapi ... Share.Snapshot list version=2 name=CCSyncTest
{"data":{"snapshots":[{"time":"GMT+08-2026.08.17-14.00.36"}],"total":1}}   # only the API-made one
```

DSM keys its list off `@<share>.meta`, so hand-rolled subvolumes are orphans
from the UI's point of view. Delete via the API when the API made it:

```
POST api=SYNO.Core.Share.Snapshot method=delete version=1
     name=CCSyncTest snapshots=["GMT+08-2026.08.17-14.00.36"]
{"success":true}
```

`/usr/syno/bin/synoschedtask` exists and lists DSM's task scheduler entries
(`synoschedtask --get`), so a scheduled snapshot *could* be created as a
generic scheduled task running `synowebapi ... Share.Snapshot create` — a
package-free path worth prototyping in WP3 rather than assuming.

### VERDICT

**Plan decision 6 ("Btrfs + Snapshot Replication as a stated requirement") is
half right and can be relaxed.**

- **Do not require the package for the snapshot capability itself.** Taking,
  listing, restoring and deleting share snapshots is base DSM. `snapshot()` in
  the `ServerBackend` interface should be `SYNO.Core.Share.Snapshot create`
  with a `synobtrfssnap -t -r` fallback — no package, no UI step.
- **Do require it (or a DSM task-scheduler task) for the *schedule*.** The
  installer's "create a scheduled snapshot task" step must (a) detect the
  package via `synopkg list --name`, (b) if present, `set_schedule`, (c) if
  absent, either create a `synoschedtask` entry calling
  `Share.Snapshot create` or fail with a clear instruction — never claim
  success.
- **Require Btrfs, not the package**, in WP7's published requirements; the
  package moves from "required" to "recommended (for the UI and retention
  policy)". That materially lowers the customer's setup burden.
- WP6's restore drill should assert ownership/ACL after restore, because
  `cp -a` silently re-owns.

---

## Left on the device

Everything below is new, is prefixed `ccsync` where it is ours, and is
intended for later phases. **The SFTP change is a change to a live NAS.**

| Item | Detail |
|---|---|
| Group `editors` | **gid 65536**, local, members `ccsync_a`, `ccsync_b`. Created with `synogroup --add editors`. |
| User `ccsync_a` | **uid 1030**, primary gid 100 (`users`), shell `/sbin/nologin`, home `/var/services/homes/ccsync_a`, description "CCSync Spike A". Created with `synouser --add`. Password held only in the scratchpad. |
| User `ccsync_b` | **uid 1031**, same shape, description "CCSync Spike B". Created with `SYNO.Core.User create` via `synowebapi`. |
| SSH keys | ed25519 `authorized_keys` installed at `/volume1/homes/{ccsync_a,ccsync_b}/.ssh/authorized_keys` (0600, owned by the user; `.ssh` 0700). **Private keys exist only in the session scratchpad** (`.../scratchpad/keys/`), never in the repo. Revoke by deleting the two `authorized_keys` files. |
| Shared folder `CCSyncTest` | `/volume1/CCSyncTest`, Btrfs subvolume ID 1654, no recycle bin, CoW on, browsable. Created with `SYNO.Core.Share create`. Contains only `Projects/demo/sub/precious.txt` (12 bytes). |
| `CCSyncTest` permissions | `administrators` RW, `editors` RW (set with `SYNO.Core.Share.Permission set`), which installed the ACE `group:editors:allow:rwxpdDaARWc--:fd--` at level 0. |
| **SFTP service ENABLED** | Was `{"enable":false,"portnum":22}`; now `{"enable":true,"portnum":22}`. Changed with `SYNO.Core.FileServ.FTP.SFTP set version=1 enable=true portnum=22`. **This is the one change to the box's live service posture.** FTP itself remains off (`enable_ftp:false`). Revert with the same call and `enable=false`. |
| `/volume1/@sharesnap/CCSyncTest/` | Created by DSM when the first snapshot was taken; now contains only DSM's own `desktop.ini`. The snapshot itself is gone. |

No existing user, group, share, package, firewall rule or service was modified.
No FTP application privilege was granted or left changed — the `SYNO.SFTP`
rule set was restored to exactly its original two entries (`everyone` allow,
`arr-user` deny) and verified.

## Removed

| Item | Verification |
|---|---|
| compose project `ccsync-spike` + `/volume1/docker/ccsync-spike/` | `docker compose ls \| grep -c ccsync` → 0; `ls /volume1/docker \| grep -i ccsync` → empty |
| container `ccsync-spike-sleeper` | `docker ps -a --filter name=ccsync` → empty |
| container `ccsync-spike-web` (nginx on 127.0.0.1:8480) | same; `netstat -tlnp \| grep 8480` → empty |
| images `alpine:3.19`, `nginx:alpine` | `docker rmi` output shows layers deleted |
| `tailscale serve` config | none was ever created (tailnet-level gate); `tailscale serve status` → `No serve config` |
| throughput file `bench2g.bin` (2 GiB) — NAS and base rig | `/volume1/CCSyncTest/bench{,_smb}` removed; local `E:\ccsync_spike_bench` removed; `df -h /volume1` back to 59 G free |
| share snapshot `GMT+08-2026.08.17-14.00.36` and two manual subvolumes | `Share.Snapshot list` → `{"snapshots":[],"total":0}`; `btrfs subvolume delete` confirmed |
| ACL scratch dirs `posixtest`, `acltest`, `addtest`, `uidtest.txt`, `rootuid.txt` | `ls -lna /volume1/CCSyncTest` shows only `@eaDir` + `Projects` |
| probe group `ccsync_probe_grp`, probe users `ccsync_probe` ×9 | `Group list` → `[administrators, editors, http, users]`; `User list` → `[admin, arr-user, Cablewrap, ccsync_a, ccsync_b, guest, vruskinfox]` |
| accidental local dir `C:\192.168.0.104\...` (a mangled UNC in a generated script) | removed |

---

## Recommended plan changes

Ordered by how much schedule they move.

1. **WP5 / correctness, do this first and independently of the port:**
   cap `sftp_chunk_size` at **64Ki** for any server running OpenSSH < 8.5.
   At 255Ki, rclone downloads from DSM 7.2 truncate at ~514 MiB and report
   `corrupted on transfer: sizes differ`. Make it a site-manifest value with a
   Synology default; keep 255Ki for lane A (upload) only. Add `shell_type` and
   `port` to the manifest at the same time — DSM editors are `/sbin/nologin`,
   so `--sftp-shell-type none` is required.

2. **WP3 / spike 1:** forbid `chmod`/`chown` under the tree share on the
   Synology backend. `chmod` deletes the Synology ACL outright (`Archive:
   None`, "It's Linux mode") and, combined with DSM's `internal-sftp -u 000`,
   leaves every new file world-writable. `set_tree_acl()` becomes: create the
   share with `Share.Permission set` (which installs the inheritable ACE
   itself), then verify with `synoacltool -get` / `-get-perm`, and repair with
   `-enforce-inherit` or `-add`. Add the "not `It's Linux mode`" assertion to
   `check_health.py`.

3. **WP2 / spike 3:** `SYNO.API.Auth` **version 7**. Version 6 yields a sid
   that can read but is refused (105, `x-request-error: noprivilege`) on every
   mutation, for a full administrators-group account. Version-gate on the
   login version, not just on `SYNO.API.Info`. Serialise every parameter as
   JSON (a Python `False` earns 3103). Always read back after
   `Group.Member add` — it returns `success:true` while ignoring a wrongly
   named parameter.

4. **Mapping table / spike 2:** replace "grant the group the **FTP application
   privilege**" with: the privilege is **`SYNO.SFTP`** (distinct from
   `SYNO.FTP`), it is `grant_by_default: true`, so `grant_sftp()` is a
   *verification* not a grant. What actually must be turned on is the **SFTP
   service**, and that is a one-line API call
   (`SYNO.Core.FileServ.FTP.SFTP set enable=true`) — move it out of WP7's
   manual prerequisites and into the installer. Also record that the SFTP
   remote root is the user's share view (`/CCSyncTest/…`, not
   `/volume1/CCSyncTest/…`) and that DSM's homes are already 711 — never
   chmod a home.

5. **WP7 / spike 8:** downgrade **Snapshot Replication from required to
   recommended**. Taking, listing, restoring and deleting share snapshots
   works on base DSM via `SYNO.Core.Share.Snapshot` and `synobtrfssnap`;
   only *scheduling* and retention need the package (403 without it).
   `snapshot()` needs no package; the installer's scheduled-task step should
   detect the package and otherwise offer a `synoschedtask` entry, and must
   never claim success when it did neither. Btrfs stays a hard requirement.

6. **WP4 / spike 4:** add "Serve/HTTPS enabled for the tailnet" as an explicit
   prerequisite with the one-time admin-console URL the CLI prints; the
   installer must treat `Serve is not enabled on your tailnet` as a failure.
   Use `--yes` with `tailscale serve --bg` or it blocks on a prompt. Note that
   DSM's own nginx owns `0.0.0.0:443/5001`, so :443 publication must go
   through serve or the DSM reverse proxy — the dashboard cannot bind it.
   `configure-host` was not needed on a unit with `TUN: true`.

7. **WP3 / spike 7:** template `${APP_UID}:${APP_GID}` from live values — on
   DSM, local users start at **1024** and local groups at **65536**
   (`editors` came out as gid 65536, nothing like TrueNAS's 3001). Refuse
   uid < 1024 and uid ≥ 170000 (package accounts). `SYNO.Core.Group create`
   returns the gid directly. No container may read mode bits on a bind-mounted
   share path — the container sees 777 where the host sees 770.

8. **WP6, unchanged but now specific:** two things were untestable on
   production hardware and must be on the validation matrix —
   **(a) reboot survival** of a CLI-started compose stack (the box has 77 days
   of uptime and cannot be rebooted; note that CLI stacks do *not* register as
   Container Manager *projects*, `SYNO.Docker.Project list` does not see
   them), and **(b) uid/gid stability across a DSM minor update**.

9. **Operational, for `GOTCHAS.md`:** the SFTP-service gate and the
   `SYNO.SFTP`-privilege gate produce the *same* client symptom (key auth
   succeeds, then `SSHException: Channel closed.`), and sshd StrictModes
   rejections are logged **nowhere** on DSM at its default LogLevel — DSM's
   sshd logs to `/var/log/auth.log`, there is no `journalctl`, and
   "Authentication refused: bad ownership or modes" never appears. Both belong
   in the gotchas file with today's date.
