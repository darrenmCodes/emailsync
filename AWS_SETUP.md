# AWS Deployment Guide — Email Engagement Sync

Deploys the Email Engagement Sync dashboard on a single EC2 instance.
Cheapest option for 3 people — a t3.micro runs this fine.

**No separate database needed.** Each user gets their own SQLite file
stored on the EC2 disk under `data/dbs/`. Notion settings are also
per-user (configurable in the sidebar).

---

## 1. Launch EC2 Instance

- **AMI**: Amazon Linux 2023 (or Ubuntu 22.04)
- **Instance type**: t3.micro (free tier eligible)
- **Storage**: 20 GB gp3
- **Security group** — open these ports:
  - SSH (22) — your IP only
  - HTTP (80) — anywhere (or restrict to your team's IPs)
  - HTTPS (443) — anywhere (if using SSL)
  - Custom TCP (8501) — anywhere (Streamlit default, only needed during setup)
- **Key pair**: create or use existing `.pem` file

## 2. SSH In

```bash
ssh -i your-key.pem ec2-user@<PUBLIC_IP>
# or for Ubuntu: ssh -i your-key.pem ubuntu@<PUBLIC_IP>
```

## 3. Install Dependencies

### Amazon Linux 2023
```bash
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git nginx
```

### Ubuntu 22.04
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git nginx
```

## 4. Deploy the App

```bash
# Clone your repo (or scp the files)
git clone <YOUR_REPO_URL> ~/email-sync
cd ~/email-sync

# Create virtualenv
python3.11 -m venv venv   # or python3 -m venv venv on Ubuntu
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Add Config Files

```bash
# Copy your Google OAuth credentials (Web Application type)
# From your local machine:
# scp -i your-key.pem credentials.json ec2-user@<PUBLIC_IP>:~/email-sync/

# Create .env (Notion settings are per-user, configured in the app sidebar)
cat > .env << 'EOF'
REDIRECT_URI=http://<PUBLIC_IP>
EOF
```

## 6. Set Up Nginx (reverse proxy on port 80)

This puts Streamlit behind Nginx so users go to `http://<your-ip>`
instead of `http://<your-ip>:8501`.

```bash
sudo tee /etc/nginx/conf.d/streamlit.conf > /dev/null << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }
}
EOF

# Remove default config if it conflicts
sudo rm -f /etc/nginx/conf.d/default.conf        # Amazon Linux
sudo rm -f /etc/nginx/sites-enabled/default       # Ubuntu

sudo nginx -t          # check config is valid
sudo systemctl enable nginx
sudo systemctl restart nginx
```

## 7. Create a Systemd Service (keeps the app running)

```bash
sudo tee /etc/systemd/system/email-sync.service > /dev/null << EOF
[Unit]
Description=Email Engagement Sync
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/email-sync
ExecStart=/home/ec2-user/email-sync/venv/bin/streamlit run app.py \
    --server.port 8501 \
    --server.address 127.0.0.1 \
    --server.headless true \
    --browser.gatherUsageStats false
Restart=always
RestartSec=5
Environment="REDIRECT_URI=http://<PUBLIC_IP>"

[Install]
WantedBy=multi-user.target
EOF
```

> **Ubuntu**: change `User=ec2-user` to `User=ubuntu`
> and update the WorkingDirectory/ExecStart paths accordingly.

```bash
sudo systemctl daemon-reload
sudo systemctl enable email-sync
sudo systemctl start email-sync

# Check it's running
sudo systemctl status email-sync
```

## 8. Update Google Cloud Console

Go to Google Cloud Console → APIs & Credentials → your Web Application OAuth client.

Add to **Authorized redirect URIs**:
```
http://<PUBLIC_IP>
```

Later, if you add a domain name:
```
https://crm.yourdomain.com
```

## 9. Verify

Visit `http://<PUBLIC_IP>` in your browser.
You should see the "Sign in with Google" page.

---

## Optional: Custom Domain + HTTPS

### Point a domain

Add an A record in your DNS:
```
crm.yourdomain.com → <PUBLIC_IP>
```

### Free SSL with Let's Encrypt

```bash
# Install certbot
sudo dnf install -y certbot python3-certbot-nginx   # Amazon Linux
# or
sudo apt install -y certbot python3-certbot-nginx    # Ubuntu

# Get certificate
sudo certbot --nginx -d crm.yourdomain.com

# Auto-renew is set up automatically. Test it:
sudo certbot renew --dry-run
```

After SSL is set up, update:
1. `.env` → `REDIRECT_URI=https://crm.yourdomain.com`
2. Systemd service → `Environment="REDIRECT_URI=https://crm.yourdomain.com"`
3. Google Cloud Console → add `https://crm.yourdomain.com` to redirect URIs
4. Restart: `sudo systemctl restart email-sync`

---

## Optional: Elastic IP

By default, the public IP changes if you stop/start the instance.
To keep a fixed IP:

1. EC2 Console → Elastic IPs → Allocate
2. Associate it with your instance
3. Update the REDIRECT_URI and Google Cloud Console with the new IP

Free while the instance is running. $3.65/month if the instance is stopped.

---

## Useful Commands

```bash
# View app logs
sudo journalctl -u email-sync -f

# Restart after code changes
cd ~/email-sync && git pull
sudo systemctl restart email-sync

# Check nginx logs
sudo tail -f /var/log/nginx/error.log
```

---

## Cost Estimate

| Resource       | Monthly Cost          |
|----------------|-----------------------|
| t3.micro       | ~$8 (or free tier)    |
| 20 GB gp3      | ~$1.60                |
| Elastic IP     | Free while running    |
| Data transfer  | Negligible for 3 users|
| **Total**      | **~$10/month**        |
