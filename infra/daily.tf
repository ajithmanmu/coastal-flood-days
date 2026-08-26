###############################################################################
# Daily refresh
#
# One Lambda, once a day, keeping the published dataset current. It refetches the
# current year for every station because NOAA revises recent observations for
# weeks -- see the module docstring in src/daily.py for why that beats appending.
###############################################################################

resource "aws_ecr_repository" "daily" {
  name                 = "coastal-flood-days-daily"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "daily" {
  repository = aws_ecr_repository.daily.name
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
# Permissions -- the function may read and write this one bucket, and nothing else
###############################################################################

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "daily" {
  name               = "coastal-flood-days-daily"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "daily" {
  statement {
    sid       = "ReadWriteData"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.daily.arn}:*"]
  }
}

resource "aws_iam_role_policy" "daily" {
  name   = "coastal-flood-days-daily"
  role   = aws_iam_role.daily.id
  policy = data.aws_iam_policy_document.daily.json
}

###############################################################################
# The function
###############################################################################

resource "aws_cloudwatch_log_group" "daily" {
  name              = "/aws/lambda/coastal-flood-days-daily"
  retention_in_days = 30
}

resource "aws_lambda_function" "daily" {
  function_name = "coastal-flood-days-daily"
  role          = aws_iam_role.daily.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.daily.repository_url}:${var.image_tag}"
  architectures = ["arm64"]

  # The job is network-bound: ~274 sequential NOAA calls, two per station. A laptop run
  # took ~5 minutes, so 600s looked generous -- until NOAA slowed us down after several
  # runs in quick succession and an invocation hit the ceiling exactly at 600000 ms.
  #
  # 900 is Lambda's maximum, and the right answer for a job whose runtime is set by how
  # fast someone else's API answers. The real protection is the alarm and the
  # refuse-to-publish guard, not a tight timeout: a slow run that finishes is fine, and a
  # run that produces nothing is already refused before it can overwrite anything.
  timeout     = 900
  memory_size = 2048

  environment {
    variables = {
      RAW_URI     = "s3://${aws_s3_bucket.data.bucket}/raw"
      RESULTS_URI = "s3://${aws_s3_bucket.data.bucket}/results"
    }
  }

  depends_on = [aws_cloudwatch_log_group.daily]
}

###############################################################################
# Schedule -- 10:00 UTC, by which point the previous GMT day is closed out and
# NOAA has published it. Flood days are counted on GMT boundaries (see rule 4).
###############################################################################

resource "aws_scheduler_schedule" "daily" {
  name                         = "coastal-flood-days-daily"
  schedule_expression          = "cron(0 10 * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.daily.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name = "coastal-flood-days-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "invoke-daily"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.daily.arn
    }]
  })
}

###############################################################################
# Alarms
#
# Two, and the second is the one that matters. A job that never runs looks
# identical to a healthy one if you only watch error counts -- that is exactly
# the gap behind MAR-886 at work, and it is the failure this pipeline is most
# likely to have.
###############################################################################

resource "aws_sns_topic" "alerts" {
  name = "coastal-flood-days-alerts"
}

resource "aws_cloudwatch_metric_alarm" "daily_errors" {
  alarm_name          = "coastal-flood-days-daily-errors"
  alarm_description   = "The daily refresh raised an error."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.daily.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "daily_did_not_run" {
  alarm_name        = "coastal-flood-days-daily-did-not-run"
  alarm_description = "The daily refresh has not succeeded in 25 hours. Silence is the failure mode this catches."

  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = aws_lambda_function.daily.function_name }
  statistic           = "Sum"
  period              = 90000 # 25h, so a slightly late run does not trip it
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"

  # Missing data IS the alarm condition here. Lambda publishes no Invocations metric at
  # all when it never runs, so treating absence as "fine" would defeat the entire alarm.
  treat_missing_data = "breaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]
}
