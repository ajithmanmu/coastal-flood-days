###############################################################################
# Custom domain
#
# floodhours.ajithmanmadhan.com. A subdomain of a domain already owned in this
# account, rather than a new registration: it costs nothing, and it keeps the
# project attached to its author -- someone who lands here can trim the hostname
# and find the portfolio.
#
# Deliberately not nested under portfolio.*. A URL that announces the work as a
# portfolio piece frames it as an exercise before the reader has seen anything,
# and the claim here is that the dataset is real.
###############################################################################

variable "domain_name" {
  description = "public hostname for the site"
  type        = string
  default     = "floodhours.ajithmanmadhan.com"
}

variable "hosted_zone" {
  description = "existing Route 53 zone that owns the parent domain"
  type        = string
  default     = "ajithmanmadhan.com"
}

# Looked up, never created. The zone predates this project and serves the
# author's other sites; Terraform destroying it would take those down too.
data "aws_route53_zone" "site" {
  name         = "${var.hosted_zone}."
  private_zone = false
}

# CloudFront only accepts certificates from us-east-1, whatever region the rest
# of the stack lives in. This stack is already us-east-1, so no second provider
# is needed -- but that is a coincidence worth stating, not a rule.
resource "aws_acm_certificate" "site" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  # Replace before destroying: swapping a certificate on a live distribution
  # otherwise leaves a window with no valid cert attached.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for opt in aws_acm_certificate.site.domain_validation_options :
    opt.domain_name => {
      name   = opt.resource_record_name
      record = opt.resource_record_value
      type   = opt.resource_record_type
    }
  }

  zone_id         = data.aws_route53_zone.site.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

# Blocks until ACM has seen the DNS record. Without this the distribution can be
# updated with a certificate that is still PENDING_VALIDATION, which fails.
resource "aws_acm_certificate_validation" "site" {
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# Alias, not CNAME: a CNAME cannot sit at a name that also needs other record
# types, and an alias to CloudFront is free where a CNAME lookup is billed.
resource "aws_route53_record" "site" {
  zone_id = data.aws_route53_zone.site.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

# IPv6. CloudFront serves it by default and a sizeable share of mobile networks
# are v6-only; without this record those clients fall back to v4 or fail.
resource "aws_route53_record" "site_v6" {
  zone_id = data.aws_route53_zone.site.zone_id
  name    = var.domain_name
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

output "site_domain" {
  value = "https://${var.domain_name}"
}
