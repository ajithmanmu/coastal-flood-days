###############################################################################
# Coastal Flood Days -- backfill task
#
# One Fargate task that walks ~14,000 station-years of NOAA water levels into S3.
# It runs for hours, once, and must be stoppable at any moment.
#
# Deliberately absent: no NAT gateway (~$32/mo would dwarf this project's entire
# bill), no load balancer, no service, no autoscaling. The task makes outbound
# HTTPS calls and nothing reaches in.
###############################################################################

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.profile

  default_tags {
    tags = {
      Project   = "coastal-flood-days"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

# The default VPC's public subnets. A public IP with no inbound rules is the right
# trade here: the task needs egress to NOAA and S3, and exposes nothing.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

###############################################################################
# Storage
###############################################################################

resource "aws_s3_bucket" "data" {
  bucket = "coastal-flood-days-data-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

###############################################################################
# Image
###############################################################################

resource "aws_ecr_repository" "backfill" {
  name                 = "coastal-flood-days"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Untagged layers pile up on every rebuild and are pure cost.
resource "aws_ecr_lifecycle_policy" "backfill" {
  repository = aws_ecr_repository.backfill.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "expire untagged images after 7 days"
      selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }
      action       = { type = "expire" }
    }]
  })
}

###############################################################################
# The kill switch
#
# Flip this and the task stops at the next station-year boundary:
#   aws ssm put-parameter --name /coastal-flood-days/backfill/enabled \
#       --value false --type String --overwrite
#
# The script reads it between years and fails OPEN -- an unreachable SSM does not
# abort a six-hour job, because the request cap, time limit and circuit breaker
# still bound the damage.
###############################################################################

resource "aws_ssm_parameter" "kill_switch" {
  name        = "/coastal-flood-days/backfill/enabled"
  description = "Set to false to stop the backfill task at its next boundary"
  type        = "String"
  value       = "true"

  # Operators flip this by hand; Terraform must not flip it back.
  lifecycle {
    ignore_changes = [value]
  }
}

###############################################################################
# Permissions
###############################################################################

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Pulls the image and writes logs. AWS's managed policy covers exactly this.
resource "aws_iam_role" "execution" {
  name               = "coastal-flood-days-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# What the code itself may do: write this one bucket, read the kill switch.
resource "aws_iam_role" "task" {
  name               = "coastal-flood-days-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "ReadWriteRawData"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    sid       = "ListBucketForCacheChecks"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
  statement {
    sid       = "ReadKillSwitch"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.kill_switch.arn]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "coastal-flood-days-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

###############################################################################
# Compute
###############################################################################

resource "aws_cloudwatch_log_group" "backfill" {
  name              = "/ecs/coastal-flood-days"
  retention_in_days = 30 # never leave a log group on "never expire"
}

resource "aws_ecs_cluster" "main" {
  name = "coastal-flood-days"
}

resource "aws_security_group" "task" {
  name        = "coastal-flood-days-task"
  description = "Outbound only: NOAA over HTTPS, S3, SSM"
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  # No ingress rules at all. Nothing connects to this task.
}

resource "aws_ecs_task_definition" "backfill" {
  family                   = "coastal-flood-days-backfill"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "ARM64" # Graviton, ~20% cheaper
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name      = "backfill"
    image     = "${aws_ecr_repository.backfill.repository_url}:${var.image_tag}"
    essential = true

    # Overridable at run time, so limits change without a rebuild.
    command = [
      "--start", tostring(var.start_year),
      "--end", tostring(var.end_year),
      "--delay", tostring(var.seconds_between_requests),
      "--max-hours", tostring(var.max_hours),
      "--max-requests", tostring(var.max_requests),
    ]

    environment = [
      { name = "RAW_URI", value = "s3://${aws_s3_bucket.data.bucket}/raw" },
      { name = "AWS_DEFAULT_REGION", value = var.region },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backfill.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "backfill"
      }
    }
  }])
}
