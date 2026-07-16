output "sagemaker_model_name" {
  description = "Name of the SageMaker model"
  value       = aws_sagemaker_model.prediction.name
}

output "sagemaker_endpoint_name" {
  description = "Name of the SageMaker serverless endpoint"
  value       = aws_sagemaker_endpoint.prediction.name
}

output "sagemaker_endpoint_arn" {
  description = "ARN of the SageMaker serverless endpoint"
  value       = aws_sagemaker_endpoint.prediction.arn
}
