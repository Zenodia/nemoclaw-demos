curl -X POST http://localhost:5678/webhook/agent-hub \
  -H "Content-Type: application/json" \
  -d '{"chatInput": "Analyze GPU cluster utilization"}'