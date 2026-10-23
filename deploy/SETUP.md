# Raspberry Pi setup checklist (Phase 4)

Follows DESIGN.md §9. Work through it in order over SSH. Commands assume the
repository is cloned to `/opt/fwcal` and run from there. Steps marked
**(Phase 3)** need the Graph fetcher and can be skipped until it exists.

## 1. Operating system
1. Flash **Raspberry Pi OS (64-bit)** with Raspberry Pi Imager. In the Imager settings:
   - set a username (the kiosk desktop user) and a strong password;
   - enable SSH with **public-key authentication only** and paste your public key;
   - set the time zone and Wi-Fi (or use Ethernet).
2. First boot, then update: `sudo apt update && sudo apt full-upgrade`.
3. Automatic security updates: `sudo apt install unattended-upgrades` and enable it
   (`sudo dpkg-reconfigure -plow unattended-upgrades`).
4. Check the clock: `timedatectl` shows the right time zone and `System clock synchronized: yes`.
5. Remove or disable services that listen and aren't needed:
   `sudo systemctl disable --now avahi-daemon.socket avahi-daemon cups cups-browsed bluetooth`
   (ignore any that aren't installed).

## 2. SSH and firewall
1. From your laptop, confirm a key login works in a **second** session.
2. Install `sshd_config.d/fwcal.conf` to `/etc/ssh/sshd_config.d/fwcal.conf`, then
   `sudo sshd -t && sudo systemctl reload ssh`. Test a new key login again before closing your session.
3. `sudo apt install nftables`; edit `nftables.conf` so the SSH rule matches your home network;
   install it to `/etc/nftables.conf`; `sudo systemctl enable --now nftables`.

## 3. Code
1. `sudo git clone <repository> /opt/fwcal` and check out the reviewed commit:
   `sudo git -C /opt/fwcal checkout <commit>`. The tree stays owned by root.
2. `sudo python3 -m venv /opt/fwcal/.venv`
3. **(Phase 3)** `sudo /opt/fwcal/.venv/bin/pip install --require-hashes --only-binary :all: --no-deps -r /opt/fwcal/requirements.txt`
4. `sudo /opt/fwcal/.venv/bin/python -m compileall -q /opt/fwcal/fwcal` (the services can't write bytecode caches).
5. Run the tests once as your own user (no sudo): `cd /opt/fwcal && /opt/fwcal/.venv/bin/python -m unittest discover -s tests -t .`

## 4. Users, directories and config
1. `sudo cp sysusers.d/fwcal.conf /etc/sysusers.d/ && sudo systemd-sysusers`
2. `sudo cp tmpfiles.d/fwcal.conf /etc/tmpfiles.d/ && sudo systemd-tmpfiles --create /etc/tmpfiles.d/fwcal.conf`
3. Create `/etc/fwcal/config.toml` from `config.example.toml` (client ID, viewer account,
   calendars, `photo_dir = "/var/lib/fwcal/photos"`), then
   `sudo chown root:fwcal /etc/fwcal/config.toml && sudo chmod 0640 /etc/fwcal/config.toml`.
4. Copy photos into `/var/lib/fwcal/photos/` (JPEG, PNG or WebP; ideally resized to about
   1080×1920), then `sudo chown root:fwcal-web /var/lib/fwcal/photos/* && sudo chmod 0640 /var/lib/fwcal/photos/*`.

## 5. Services
1. `sudo cp systemd/fwcal-web.socket systemd/fwcal-web.service systemd/fwcal-sync.service systemd/fwcal-sync.timer /etc/systemd/system/`
2. `sudo systemctl daemon-reload && sudo systemctl enable --now fwcal-web.socket`
3. **(Phase 3)** Sign in once as the sync user:
   `sudo -u fwcal-sync /opt/fwcal/.venv/bin/python -m fwcal auth login`
   (it refuses any account other than `expected_account`).
4. **(Phase 3)** `sudo systemctl enable --now fwcal-sync.timer`
5. Check the sandboxes: `systemd-analyze security fwcal-web.service fwcal-sync.service`.

## 6. Kiosk
1. `sudo apt install chromium wlr-randr`
2. `sudo mkdir -p /etc/chromium/policies/managed && sudo cp chromium/fwcal-policy.json /etc/chromium/policies/managed/`
   Check at `chrome://policy` once, before the URL blocklist hides it (or trust `test_deploy.py`).
3. Desktop auto-login for the kiosk user: `sudo raspi-config` → System → Boot / Auto Login → Desktop Autologin.
4. Copy `kiosk/autostart` to `~/.config/labwc/autostart` for the kiosk user; set the output
   name from `wlr-randr`.
5. **Touch mapping:** after rotating, map the touch screen to the rotated output in
   `~/.config/labwc/rc.xml` (`<touch deviceName="..." mapToOutput="HDMI-A-1" />`, device name
   from `libinput list-devices`), or taps land in the wrong place.
6. Reboot. The calendar should appear full-screen.

## 7. Verify
1. `sudo /opt/fwcal/.venv/bin/python -m fwcal check`: no FAIL lines.
2. `sudo ss -tulpn`: only sshd and `127.0.0.1:8765` (held by systemd).
3. From another machine on the network, `http://<pi-address>:8765/` must **not** load.
4. Unplug the network for 10 minutes: the calendar stays up; the status turns amber, then red after an hour.
5. Run spike S3 (DESIGN §12.3): CPU, memory and frame rate over 24 hours.

## If the Pi is lost or stolen
Follow the revocation runbook in DESIGN.md §11.3: remove the calendar shares first.
