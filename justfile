deploy:
  eval "$(aws s3 cp s3://ycgs-use1-terraform/ycgs/newhaven-multires-bucket - | jq -r '.outputs.deploy_commands.value')"
