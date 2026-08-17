variable "region" {
  type    = string
  default = "us-east-1"
}

variable "profile" {
  type    = string
  default = "iamadmin-projects-prod"
}

variable "image_tag" {
  type    = string
  default = "latest"
}

# 0.5 vCPU / 1 GB. The job waits on NOAA far more than it computes; the memory is
# there for pyarrow, not for throughput.
variable "task_cpu" {
  type    = number
  default = 512
}

variable "task_memory" {
  type    = number
  default = 1024
}

variable "start_year" {
  type    = number
  default = 1920
}

variable "end_year" {
  type    = number
  default = 2025
}

# NOAA publishes no rate limit and asks callers to be reasonable. Half a second
# between requests is roughly 2/sec, which is polite for a public API and still
# finishes ~14,000 station-years inside the time limit.
variable "seconds_between_requests" {
  type    = number
  default = 0.5
}

variable "max_hours" {
  type    = number
  default = 8
}

variable "max_requests" {
  type    = number
  default = 20000
}
