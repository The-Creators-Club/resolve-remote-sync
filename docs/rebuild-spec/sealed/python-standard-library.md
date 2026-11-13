# Sealed notes: python-standard-library

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 4 notes.

### APP-S11: The app trusted expired Windows store certificates that Windows itself ignores.
- Why: The default secure context loads every certificate from the Windows stores, expired or not, and a connection object made before a fix keeps the old trust.
- Must: Expired store certificates are filtered out before any secure connection object is created.
- Tool: Python ssl loading the Windows certificate stores
- Where it bit: The app on each editor's computer

### SRV-S14: The HTTP library re-sends custom key headers and form bodies across redirects.
- Why: On a cross-host redirect the library drops only the standard authorisation header; a form body and any custom key header go to the new host.
- Must: Every request carrying a credential in a body or custom header turns redirect-following off explicitly and refuses any redirect response.
- Tool: Python requests and urllib urlopen
- Where it bit: The server: installing it and keeping it running

### SRV-S15: Upgrading a mail connection to encryption checked neither host nor certificate.
- Why: Upgrading the connection without an explicit context verifies neither the host name nor the certificate.
- Must: Alert mail verifies the mail server's certificate and host name, with only an explicit admin opt-out for a self-signed relay.
- Tool: Python smtplib starttls()
- Where it bit: The server: installing it and keeping it running

### SYN-S35: A time-limited child-process wait could still hang forever on Windows.
- Why: After killing a child on timeout, the call waits for its output pipes to close, which never happens when a grandchild inherited them.
- Must: Every wait on a child process has a hard limit, and a run cut off is reported as "could not tell", never as an empty result.
- Tool: Python subprocess.run(timeout=) on Windows
- Where it bit: Sync
