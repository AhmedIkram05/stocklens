# Implementation Plan: Expose MLflow & Airflow GUIs via ALB

## Overview

Both MLflow (port 5000) and Airflow webserver (port 8080) run as Fargate services in private subnets with no ALB target groups or listener rules — only reachable from other ECS tasks via Cloud Map DNS. This plan exposes both GUIs through the existing ALB so they're accessible from a browser, same as they were in Docker.

## Critical Discovery: ALB Doesn't Strip Path Prefixes

ALB path-based routing forwards the **entire original path** to the target. MLflow handles this natively (`--path-prefix`). Airflow does **not** natively support a URL prefix — its Flask routes are at `/login`, `/dags`, etc. Sending `/airflow/login` would 404.

**Therefore Option A (path-based routing) doesn't work cleanly for Airflow without an nginx sidecar.** The revised approach uses **separate listener ports** on the existing ALB:

| Service     | ALB Port      | Target Port | URL                  | App Config Change       |
| ----------- | ------------- | ----------- | -------------------- | ----------------------- |
| Backend API | 80 (existing) | 8000        | `http://<alb>/`      | None                    |
| MLflow      | 5001 (new)    | 5000        | `http://<alb>:5001/` | None (no prefix needed) |
| Airflow     | 8080 (new)    | 8080        | `http://<alb>:8080/` | None (no prefix needed) |

This requires zero app-level changes — both tools serve at root, which is what they expect. Add DNS aliases (e.g., `mlflow.stocklens.com → ALB:5001`) later when ready.

## Requirements

- Access MLflow UI at `http://<alb-dns>:5001`
- Access Airflow UI at `http://<alb-dns>:8080`
- Backend API continues working unchanged at `http://<alb-dns>/` (port 80)
- Zero application-level config changes (no path prefix hacks)
- Security groups scoped: only ALB SG can reach these new ports

## Architecture Changes

### 1. `terraform/modules/compute/main.tf` — Add target groups + listeners

- Add `aws_lb_target_group` for MLflow (port 5000, health check `/`)
- Add `aws_lb_target_group` for Airflow (port 8080, health check `/api/v2/monitor/health`)
- Add `aws_lb_listener` for port 5001 → MLflow TG
- Add `aws_lb_listener` for port 8080 → Airflow TG

### 2. `terraform/modules/compute/outputs.tf` — Expose new resources

- Output `mlflow_tg_arn` and `airflow_tg_arn` (for potential future use)

### 3. `terraform/modules/network/main.tf` — Add SG rules

- ALB SG: ingress on ports 5001 and 8080 from `0.0.0.0/0`
- MLflow SG: ingress on port 5000 from ALB SG
- Airflow SG: ingress on port 8080 from ALB SG

### 4. `terraform/modules/airflow/main.tf` — Add port mapping to webserver

- Add `portMappings` for port 8080 to the webserver container definition
- Add ALB health check (the airlow image already has a health check at `/api/v2/monitor/health`)
- Register the webserver ECS service with the Airflow target group (via `load_balancer` block)

### 5. `terraform/modules/mlflow/main.tf` — Register with ALB

- Register the MLflow ECS service with the MLflow target group (via `load_balancer` block)

### 6. `terraform/main.tf` — Wire dependencies

- Pass `module.compute.mlflow_tg_arn` → `module.mlflow`
- Pass `module.compute.airflow_tg_arn` → `module.airflow`

## Implementation Steps

### Phase 1: Security Groups — Allow traffic from ALB to MLflow/Airflow

#### Step 1: Add ALB ingress rules for new ports

**File:** `terraform/modules/network/main.tf`

Add two new ingress rules on the ALB security group for ports 5001 and 8080:

```hcl
resource "aws_security_group_rule" "alb_ingress_mlflow" {
  security_group_id = aws_security_group.alb.id
  type              = "ingress"
  from_port         = 5001
  to_port           = 5001
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "MLflow UI from anywhere"
}

resource "aws_security_group_rule" "alb_ingress_airflow" {
  security_group_id = aws_security_group.alb.id
  type              = "ingress"
  from_port         = 8080
  to_port           = 8080
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "Airflow UI from anywhere"
}
```

#### Step 2: Add MLflow SG ingress from ALB

**File:** `terraform/modules/network/main.tf`

```hcl
resource "aws_security_group_rule" "mlflow_ingress_alb" {
  security_group_id        = aws_security_group.mlflow.id
  type                     = "ingress"
  from_port                = 5000
  to_port                  = 5000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "Allow MLflow port 5000 from ALB"
}
```

#### Step 3: Add Airflow SG ingress from ALB

**File:** `terraform/modules/network/main.tf`

```hcl
resource "aws_security_group_rule" "airflow_ingress_alb" {
  security_group_id        = aws_security_group.airflow.id
  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "Allow Airflow port 8080 from ALB"
}
```

### Phase 2: ALB Target Groups + Listeners

#### Step 4: Add MLflow target group

**File:** `terraform/modules/compute/main.tf`

```hcl
resource "aws_lb_target_group" "mlflow" {
  name        = "${var.app_name}-mlflow-${var.environment}"
  port        = 5000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    path                = "/"
    port                = 5000
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  tags = {
    Name = "${var.app_name}-mlflow-tg-${var.environment}"
  }
}
```

#### Step 5: Add Airflow target group

**File:** `terraform/modules/compute/main.tf`

```hcl
resource "aws_lb_target_group" "airflow" {
  name        = "${var.app_name}-airflow-${var.environment}"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    path                = "/api/v2/monitor/health"
    port                = 8080
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  tags = {
    Name = "${var.app_name}-airflow-tg-${var.environment}"
  }
}
```

#### Step 6: Add ALB listeners for MLflow (5001) and Airflow (8080)

**File:** `terraform/modules/compute/main.tf`

```hcl
resource "aws_lb_listener" "mlflow" {
  load_balancer_arn = aws_lb.main.arn
  port              = 5001
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mlflow.arn
  }
}

resource "aws_lb_listener" "airflow" {
  load_balancer_arn = aws_lb.main.arn
  port              = 8080
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.airflow.arn
  }
}
```

#### Step 7: Output TG ARNs from compute module

**File:** `terraform/modules/compute/outputs.tf`

```hcl
output "mlflow_tg_arn" {
  description = "ARN of the MLflow ALB target group"
  value       = aws_lb_target_group.mlflow.arn
}

output "airflow_tg_arn" {
  description = "ARN of the Airflow ALB target group"
  value       = aws_lb_target_group.airflow.arn
}
```

### Phase 3: ECS Service Registration with ALB

#### Step 8: Add port mapping to Airflow webserver

**File:** `terraform/modules/airflow/main.tf`

The `local.airflow_container` doesn't have portMappings because the scheduler doesn't need them. The webserver needs them though. Add a `portMappings` block:

In the webserver task definition's container definition, merge in port mappings. Since `local.airflow_container` is shared between webserver and scheduler, override it for the webserver.

Change the webserver container definition from:

```hcl
container_definitions = jsonencode([merge(
  local.airflow_container,
  { entryPoint = [...], command = [...] }
)])
```

To:

```hcl
container_definitions = jsonencode([merge(
  local.airflow_container,
  {
    entryPoint = [...],
    command = [...],
    portMappings = [
      {
        containerPort = 8080
        hostPort      = 8080
        protocol      = "tcp"
      }
    ]
  }
)])
```

#### Step 9: Register Airflow webserver with target group

**File:** `terraform/modules/airflow/main.tf`

Add `load_balancer` block to the webserver ECS service:

```hcl
resource "aws_ecs_service" "webserver" {
  # ... existing config ...

  load_balancer {
    target_group_arn = var.airflow_tg_arn
    container_name   = "airflow"
    container_port   = 8080
  }

  # ... rest of existing config ...
}
```

Add `airflow_tg_arn` to variables:
**File:** `terraform/modules/airflow/variables.tf`

```hcl
variable "airflow_tg_arn" {
  description = "ARN of the ALB target group for Airflow webserver"
  type        = string
}
```

#### Step 10: Register MLflow with target group

**File:** `terraform/modules/mlflow/main.tf`

Add `load_balancer` block to the MLflow ECS service:

```hcl
resource "aws_ecs_service" "mlflow" {
  # ... existing config ...

  load_balancer {
    target_group_arn = var.mlflow_tg_arn
    container_name   = "mlflow"
    container_port   = 5000
  }

  # ... rest of existing config ...
}
```

Add `mlflow_tg_arn` to variables:
**File:** `terraform/modules/mlflow/variables.tf`

```hcl
variable "mlflow_tg_arn" {
  description = "ARN of the ALB target group for MLflow"
  type        = string
}
```

### Phase 4: Wire it all together in root module

#### Step 11: Pass TG ARNs to MLflow and Airflow modules

**File:** `terraform/main.tf`

Pass the new outputs to MLflow and Airflow modules:

```hcl
module "mlflow" {
  # ... existing vars ...
  mlflow_tg_arn = module.compute.mlflow_tg_arn
}

module "airflow" {
  # ... existing vars ...
  airflow_tg_arn = module.compute.airflow_tg_arn
}
```

### Phase 5: Output the new URLs

#### Step 12: Add output URLs for convenience

**File:** `terraform/outputs.tf`

```hcl
output "mlflow_ui_url" {
  description = "MLflow tracking UI URL"
  value       = "http://${module.compute.alb_dns_name}:5001"
}

output "airflow_ui_url" {
  description = "Airflow webserver UI URL"
  value       = "http://${module.compute.alb_dns_name}:8080"
}
```

## Files Changed (11 total)

| File                                     | Change                                                                    | Risk   |
| ---------------------------------------- | ------------------------------------------------------------------------- | ------ |
| `terraform/modules/network/main.tf`      | Add 3 SG rules (ALB ingress 5001, 8080; MLflow/Airflow ingress from ALB)  | Low    |
| `terraform/modules/compute/main.tf`      | Add 2 target groups + 2 listeners                                         | Low    |
| `terraform/modules/compute/outputs.tf`   | Add 2 outputs                                                             | Low    |
| `terraform/modules/airflow/main.tf`      | Add `portMappings` to webserver, add `load_balancer` to webserver service | Medium |
| `terraform/modules/airflow/variables.tf` | Add `airflow_tg_arn` variable                                             | Low    |
| `terraform/modules/mlflow/main.tf`       | Add `load_balancer` to MLflow service                                     | Medium |
| `terraform/modules/mlflow/variables.tf`  | Add `mlflow_tg_arn` variable                                              | Low    |
| `terraform/main.tf`                      | Pass TG ARNs to modules                                                   | Low    |
| `terraform/outputs.tf`                   | Add UI URLs                                                               | Low    |

## Testing Strategy

1. **`terraform plan`** — verify new resources are created without destroying existing ones
2. **`terraform apply`** — deploy changes (services will roll with new config)
3. **Health checks** — verify MLflow (`/`) and Airflow (`/api/v2/monitor/health`) pass
4. **Browser test** — open `http://<alb-dns>:5001` and `http://<alb-dns>:8080`
5. **Existing API** — confirm `http://<alb-dns>/health` still works

## Risks & Mitigations

- **Risk**: Adding `load_balancer` block to an existing ECS service forces a replacement
  - **Mitigation**: ECS will create new tasks and deregister old ones. Set `force_new_deployment = true` (or trigger manually after apply) to ensure smooth transition. The deployment circuit breaker (already enabled on MLflow) handles rollback.
- **Risk**: ALB health check for MLflow (`/`) might not return 200 immediately after startup
  - **Mitigation**: MLflow responds 200 on `/` once the server is ready. The health check has `unhealthy_threshold = 3` and `interval = 30s` — up to 90s grace period.
- **Risk**: Port 5001 or 8080 might be blocked by corporate firewalls
  - **Mitigation**: Add DNS aliases later (e.g., `mlflow.stocklens.com → ALB:5001` with a CNAME). Or switch to host-based routing once DNS is set up.

## Future Considerations

- **Add authentication** — MLflow and Airflow are exposed without auth. Add ALB OIDC integration or WAF rules for production.
- **DNS aliases** — Once Route53 is configured, add CNAME/Alias records so `mlflow.stocklens.com` and `airflow.stocklens.com` resolve to the ALB on appropriate ports.
- **HTTPS** — Add ACM cert + HTTPS listeners (already commented in code).
- **Switch to host-based routing** — When DNS is ready, swap port-based listeners for host-based rules on port 443, for cleaner URLs.

## Success Criteria

- [ ] `terraform plan` shows only the intended new resources (no destructive changes to existing)
- [ ] MLflow UI accessible at `http://<alb-dns>:5001`
- [ ] Airflow UI accessible at `http://<alb-dns>:8080`
- [ ] Backend API still works at `http://<alb-dns>/`
- [ ] Health checks pass for all three target groups
