# Joins aimed at server-install-and-running-2

## Checked

- J1 | F1
- J2 | F2, F3, F4
- J3 | F5, F6, F7, F8, F9
- J4 | fine

## Findings

### F1: Joining the private network is a prerequisite before installing in one piece, a set-up wizard step after installing in the other
- Kind: contradiction
- From: server-install-and-running-1 / What a NAS must have before the server goes on it
- Here: Connections and credentials / The server joins the private network and publishes the dashboard there with https
- From says: "Before installing, the studio needs: ... the NAS joined to the studio's private network, which is how the dashboard is reached"
- Here says: "The set-up wizard carries an optional task, \"Connect to your private network\" ... It signs the server in to the studio's private network" and "to do: the server is not signed in yet, with the link to open to add it to the network"
- Settled by: the owner must say: does the person installing join the NAS to the studio's private network before installing the server, or does the set-up wizard sign the server in to it with a link the admin opens?
- Fix: whichever is chosen, server-install-and-running-1 drops the NAS-joined prerequisite (if the wizard joins it) or this piece drops the "not signed in yet, with the link" state and sign-in action (if it is a prerequisite).

### F2: The private-network set-up task has two names, two buttons and two descriptions
- Kind: differs
- From: server-install-and-running-1 / Set-up task: reaching the dashboard over the private network
- Here: Connections and credentials / The server joins the private network and publishes the dashboard there with https
- From says: "The tasks, in order: ... then the optional ones: reaching the dashboard over the private network, the server's way in to the NAS, ..."
- Here says: "an optional task, \"Connect to your private network\", with the button \"SIGN IN OR PUBLISH\" and a CHECK"
- Settled by: OWNER_REQUIREMENTS.md 1: "One way to do each thing" (one task, one name)
- Fix: server-install-and-running-1 names the task "Connect to your private network" in its task list and heading and points here for its states and button, so the task is described once.

### F3: The private-network task turns done on "signed in and published", where the other piece requires the dashboard to answer from outside the server
- Kind: contradiction
- From: server-install-and-running-1 / Set-up task: reaching the dashboard over the private network
- Here: Connections and credentials / The server joins the private network and publishes the dashboard there with https
- From says: "This task turns done only when the dashboard really answers over the private network at a valid secure address, as seen from outside the server; answering only to the server itself is not enough."
- Here says: "Signed in and published with https | ok" and "The dashboard's address is already an address on the private network | ok"
- Settled by: SRV-030 (situation, weaker than a ruling): "The publishing step turns green only when the dashboard answers over the private network at a valid secure address."
- Fix: this piece's state table turns "ok" only when the dashboard answers at its secure private-network address as seen from outside the server, and the "address is already an address on the private network" row is removed or made to require the same answer.

### F4: Where the dashboard answers: the studio's network address in one piece, only the NAS itself and the private network in the other (not named by the join)
- Kind: contradiction
- From: server-install-and-running-1 / The server answers only on the studio's networks and comes back by itself (noticed under J2)
- Here: Connections and credentials / The dashboard is reached only through the studio's private network
- From says: "The server answers on its address on the studio's network and on the private network, never on every address; the default port is 8480."
- Here says: "On the NAS the dashboard answers only on the NAS itself and on its publication on the private network, never on every address the NAS has."
- Settled by: decisions page 12, 12.1, ANSWERED 2026-11-24 with the recommendation A: "dashboard only on the NAS itself and the private network"
- Fix: server-install-and-running-1 changes "on its address on the studio's network and on the private network" to "only on the NAS itself and on its publication on the private network".

### F5: TrueNAS: piece 1 accepts the NAS administrator's password, this piece never holds it and refuses it
- Kind: contradiction
- From: server-install-and-running-1 / The server's way in to the NAS
- Here: Connections and credentials / The server holds a limited key for a TrueNAS and never its administrator password
- From says: "On TrueNAS, a limited access key for a dedicated account (preferred), or the NAS administrator's password; the two are never sent together."
- Here says: "On TrueNAS the server never holds the NAS administrator's password." and "a TrueNAS given a password: \"a TrueNAS NAS is connected with an API key, never the admin password...\"" and "Installing or updating the server on TrueNAS without such a key is refused"
- Settled by: SRV-119 (situation, weaker than a ruling): "the server holds only a scoped NAS key"
- Fix: server-install-and-running-1 drops "or the NAS administrator's password" and the "never sent together" clause, and says the TrueNAS way in is the limited key only.

### F6: The NAS set-up task has two names
- Kind: differs
- From: server-install-and-running-1 / The server's way in to the NAS
- Here: Connections and credentials / The admin connects the server to the NAS once in the set-up wizard
- From says: "entered in set-up's \"the server's way in to the NAS\" task"
- Here says: "The set-up wizard's optional task \"Connect to your NAS\""
- Settled by: OWNER_REQUIREMENTS.md 1: "One way to do each thing" (one task, one name)
- Fix: server-install-and-running-1 calls the task "Connect to your NAS" in its heading and task list.

### F7: The NAS certificate setting is listed twice under two names
- Kind: differs
- From: server-install-and-running-1 / The server's way in to the NAS
- Here: Connections and credentials / The product makes sure it is talking to the studio's own NAS
- From says: "Setting: Trusting the NAS's certificate. Does: decides whether the server remembers the NAS's first certificate, holds to one the admin pins, or checks it against the usual authorities. Default: remember the first one seen."
- Here says: "Setting: the NAS's identity. Does: decides which NAS the product will send passwords, keys and account changes to. Default: the identity seen at first connection, recorded." (and a fourth choice: "give the studio's own certificate authority")
- Settled by: OWNER_REQUIREMENTS.md 5: "Every page, part and setting therefore has a plain name" and 1: "one place a setting comes from"; decisions page 12, 12.2 answered A
- Fix: server-install-and-running-1 removes its setting line and points to "the NAS's identity" here, which keeps the full list of choices including the studio's own certificate authority.

### F8: The NAS's remote-shell identity is remembered and checked in piece 1, but this piece, which describes the NAS's identity in full, never mentions it
- Kind: missing
- From: server-install-and-running-1 / The server's way in to the NAS
- Here: nowhere (The product makes sure it is talking to the studio's own NAS covers only the certificate)
- From says: "The NAS's remote-shell identity is remembered the same way, and a different one, or a damaged record of it, is refused."
- Here says: nothing
- Settled by: SRV-119 (situation, weaker than a ruling): "Admin connections pin the NAS host key and refuse a change"
- Fix: this piece's "The product makes sure it is talking to the studio's own NAS" adds that every identity the NAS presents on a connection carrying a password, key or account change (its certificate and its remote-shell identity alike) is recorded at first connection and a change refused, and piece 1 points here instead of saying it.

### F9: Synology sign-in failures and the session retry are described in full in both pieces, already with different lists
- Kind: said twice
- From: server-install-and-running-1 / The server's way in to the NAS
- Here: Connections and credentials / A Synology must run DSM 7 with every service the product needs
- From says: "wrong account or password; account disabled; no permission to sign in; a two-step code is needed (\"give the dashboard an account with two-step sign-in off\"); wrong two-step code. An expired session is retried once; any other DSM error is given with its number"
- Here says: "the session expired: the product signs in again once, and a second expiry is reported; invalid account or password; the account may not sign in to DSM; a two-factor code is needed; ... anything else: \"DSM error\" and its number."
- Settled by: OWNER_REQUIREMENTS.md 1: "One way to do each thing" (one description of what the person is told; the union of both lists is the safe reading, since this piece lacks "account disabled" and "wrong two-step code")
- Fix: this piece keeps one full list holding both sets of answers (adding "account disabled", "wrong two-step code" and the advice to use an account with two-step sign-in off), and piece 1 replaces its list with a pointer here.
