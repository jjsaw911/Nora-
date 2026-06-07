# Nora SSH tunnel

Forwards your local **`http://localhost:8080`** to **`localhost:8080`** on the
remote box `154.59.156.22`, so you can reach a service running there as if it
were local.

Equivalent to running:

```sh
ssh -p 43010 root@154.59.156.22 -L 8080:localhost:8080
```

> Run all of this from **your own machine** — not from a CI/sandbox, which
> can't reach the remote host.

## Connection details

| Setting        | Value             |
| -------------- | ----------------- |
| Host           | `154.59.156.22`   |
| Port           | `43010`           |
| User           | `root`            |
| Local forward  | `8080 -> localhost:8080` |

## Files

- `ssh/config` — an SSH `Host nora-tunnel` block you can include/copy into `~/.ssh/config`.
- `tunnel.sh` — a standalone connect script (no SSH config changes needed).
- `keys/joseph-mac.pub` — the public key authorized to log in (`joseph-mac`).

## 1. One-time setup: authorize your key on the server

The tunnel is passwordless only once your **public** key is in `root`'s
`authorized_keys` on the remote box. From your Mac:

```sh
# Easiest — copies your key and appends it correctly:
ssh-copy-id -i keys/joseph-mac.pub -p 43010 root@154.59.156.22
```

Or do it manually (if `ssh-copy-id` isn't available):

```sh
cat keys/joseph-mac.pub | ssh -p 43010 root@154.59.156.22 \
  'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

Both prompt for the server password the first time; after that, key auth works.

## 2. Connect

**Option A — via the script:**

```sh
./tunnel.sh                 # opens a remote shell with the tunnel active
./tunnel.sh --tunnel-only   # forward only, no shell (good for backgrounding)
```

Override any value with env vars, e.g. `LOCAL_PORT=9090 ./tunnel.sh`.

**Option B — via SSH config:**

Add to the top of `~/.ssh/config`:

```sshconfig
Include ~/path/to/this/repo/ssh/config
```

(or paste the `Host nora-tunnel` block in directly), then:

```sh
ssh nora-tunnel
```

## 3. Verify

With the tunnel open, in another terminal:

```sh
curl -v http://localhost:8080/
```

or just open <http://localhost:8080> in a browser.

## Troubleshooting

- **`bind: Address already in use`** — local `8080` is taken. Use a different
  local port: `LOCAL_PORT=9090 ./tunnel.sh` (then browse `localhost:9090`).
- **`Permission denied (publickey)`** — your key isn't authorized yet (redo
  step 1) or `IdentityFile` in `ssh/config` points at the wrong private key.
- **`channel ... open failed: connect failed`** — nothing is listening on
  `localhost:8080` *on the remote*; start the remote service first.
- **Connection hangs / drops** — the keepalive settings
  (`ServerAliveInterval`/`ServerAliveCountMax`) already retry; check the host,
  port `43010`, and any firewall in between.
- **Confirm the forward is active** — add `-v` (e.g. `./tunnel.sh -v`) and look
  for `Local forwarding listening on ... port 8080`.
