# INF-H1 — moving the production state from `environment=dev`

The production backend bucket (`stocklens/production/terraform.tfstate`) still
contains resources created with `environment=dev`, including the RDS instance.
Changing `environment` to `production` without moving state makes Terraform
destroy and recreate those resources. This is a maintenance-window operation,
not a code change.

1. Freeze deploys (`AWS_DEPLOY_ENABLED` off) and take an RDS snapshot.
2. `terraform state list > before.txt`.
3. For each name-suffixed resource (RDS, DB subnet group, ALB, ALB logs bucket,
   ElastiCache replication group + subnet group, three security groups), move it:
   `terraform state mv <dev-address> <production-address>`.
4. Run `terraform plan -var-file=dev.tfvars.json` with `environment=production`
   and confirm **no destroy/replace** for the moved resources.
5. Apply during the window; verify the backend task starts and `/health` is 200.
6. Keep `before.txt` and the plan output with the change record.

Do not flip the CI `-var environment` until step 4 is clean.

See `docs/REMEDIATION-STATUS.md` for the live remainder after this move.
