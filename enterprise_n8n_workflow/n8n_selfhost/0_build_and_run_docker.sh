# Create persistent volume
docker volume create n8n_data

# Start n8n
#
# Fresh build: n8n generates its own encryption key on first start.
# Re-deploy (to decrypt credentials-export.json on another machine): pass the
# saved key from encryption-key.txt via N8N_ENCRYPTION_KEY — see
# preserving_n8n_workflow_for_reuse_steps.md.
docker run -d --name n8n \
  -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  -e N8N_BASIC_AUTH_ACTIVE=true \
  -e N8N_BASIC_AUTH_USER=admin \
  -e N8N_BASIC_AUTH_PASSWORD=changeme \
  `# -e N8N_ENCRYPTION_KEY="$(cat encryption-key.txt)"  # uncomment for re-deploy` \
  docker.n8n.io/n8nio/n8n_