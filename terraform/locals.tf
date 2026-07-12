/**
 * locals.tf
 * StockLens — local values for VPC/subnet fallback logic.
 *
 * When vpc_id / subnet_ids are provided via variables, those are used.
 * When omitted, the VPC module creates them and the module outputs are
 * referenced instead.
 */
locals {
  # Use var.vpc_id as the single guard: if provided, all network vars
  # come from variables. If empty, VPC module (count=1) provides them.
  vpc_id             = var.vpc_id != "" ? var.vpc_id : module.vpc[0].vpc_id
  private_subnet_ids = var.vpc_id != "" ? var.private_subnet_ids : module.vpc[0].private_subnet_ids
  public_subnet_ids  = var.vpc_id != "" ? var.public_subnet_ids : module.vpc[0].public_subnet_ids
}
