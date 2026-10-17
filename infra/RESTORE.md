# Recuperação de desastre

Os backups ficam em dois lugares:

| Onde | O quê | Retenção |
|---|---|---|
| Object Storage (bucket `S3_BUCKET`, pasta `<projeto>/`) | Litestream: replicação contínua, com atraso máximo de `LITESTREAM_SYNC_INTERVAL` | 7 dias de point-in-time |
| `/var/backups/sqlite/<projeto>/AAAA-MM-DD.db` na VM | Snapshot diário (04:00 UTC) | 7 dias |

## Restaurar um banco na mesma VM

```bash
sudo systemctl stop app-<projeto>          # o backend não pode estar escrevendo
sudo systemctl stop litestream
sudo mv /var/lib/sqlite/<projeto>/app.db{,.quebrado}
sudo rm -f /var/lib/sqlite/<projeto>/app.db-{wal,shm}

# opção A: último estado do Object Storage
sudo bash -c 'set -a; . /etc/default/litestream; set +a; litestream restore -config /etc/litestream.yml /var/lib/sqlite/<projeto>/app.db'
# opção B: um ponto no tempo
sudo bash -c 'set -a; . /etc/default/litestream; set +a; litestream restore -config /etc/litestream.yml -timestamp 2026-10-17T12:00:00Z /var/lib/sqlite/<projeto>/app.db'
# opção C: snapshot local
sudo cp /var/backups/sqlite/<projeto>/2026-10-17.db /var/lib/sqlite/<projeto>/app.db

sudo chown app-<projeto>:app-<projeto> /var/lib/sqlite/<projeto>/app.db
sudo -u app-<projeto> sqlite3 /var/lib/sqlite/<projeto>/app.db 'PRAGMA integrity_check; PRAGMA journal_mode=WAL;'
sudo systemctl start litestream app-<projeto>
```

## VM perdida

1. Criar uma VM nova (Ubuntu 22.04 ou mais novo, x86_64) e apontar o DNS para o IP novo.
2. Atualizar os secrets `REMOTE_HOST` e `SSH_KNOWN_HOSTS` (`ssh-keyscan <ip>`) no GitHub.
3. Reemitir o certificado **antes** do workflow, porque a config versionada do Nginx aponta para os arquivos do Let's Encrypt e o `nginx -t` falha sem eles:
   `sudo apt install -y nginx && sudo snap install --classic certbot && sudo certbot --nginx -d manasomali.com -d www.manasomali.com`
4. Rodar o workflow **Infra** manualmente (Actions → Infra → Run workflow). Ele cria usuários, pastas e bancos **vazios**.
5. Para cada projeto, seguir "Restaurar um banco na mesma VM" (opção A).
6. Rodar o workflow **Publish Website** e os deploys dos backends.

## Testar a restauração

O workflow **Verificar backups** faz isso toda segunda. Para rodar na hora: Actions → Verificar backups → Run workflow.
