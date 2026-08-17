output "ecr_repository_url" {
  value = aws_ecr_repository.backfill.repository_url
}

output "bucket" {
  value = aws_s3_bucket.data.bucket
}

output "run_task_command" {
  description = "Start the backfill."
  value = join(" ", [
    "aws ecs run-task",
    "--cluster ${aws_ecs_cluster.main.name}",
    "--task-definition ${aws_ecs_task_definition.backfill.family}",
    "--launch-type FARGATE",
    "--network-configuration 'awsvpcConfiguration={subnets=[${join(",", slice(data.aws_subnets.default.ids, 0, 2))}],securityGroups=[${aws_security_group.task.id}],assignPublicIp=ENABLED}'",
    "--profile ${var.profile} --region ${var.region}",
  ])
}

output "stop_command" {
  description = "Flip the kill switch. The task stops at its next station-year boundary."
  value       = "aws ssm put-parameter --name ${aws_ssm_parameter.kill_switch.name} --value false --type String --overwrite --profile ${var.profile} --region ${var.region}"
}

output "resume_command" {
  value = "aws ssm put-parameter --name ${aws_ssm_parameter.kill_switch.name} --value true --type String --overwrite --profile ${var.profile} --region ${var.region}"
}

output "logs_command" {
  description = "Follow progress."
  value       = "aws logs tail ${aws_cloudwatch_log_group.backfill.name} --follow --profile ${var.profile} --region ${var.region}"
}
