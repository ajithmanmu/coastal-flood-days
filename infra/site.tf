###############################################################################
# Hosting
#
# One CloudFront distribution serving both the page and the data from the same
# bucket. Same origin means no CORS, and the edge absorbs traffic that would
# otherwise hit S3 on every page load.
#
# The bucket stays PRIVATE. CloudFront reads it through Origin Access Control,
# so nothing is world-readable -- opening the prefix would work but is a worse
# posture for no gain.
###############################################################################

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "coastal-flood-days"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Managed policies. CachingOptimized honours the Cache-Control the writer sets,
# which is what we want: the JSON carries its own max-age from storage.py.
data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "coastal-flood-days"
  price_class         = "PriceClass_100" # NA + EU; the audience is US-coastal

  origin {
    domain_name              = aws_s3_bucket.data.bucket_regional_domain_name
    origin_id                = "s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Only this distribution may read the bucket, and only the objects the page needs.
#
# Scoping this matters: granting /* let the whole 736 MB raw archive be pulled through
# CloudFront by anyone who guessed a key. The bucket was still private to direct S3
# access, so the distribution was the only way in -- and it was wide open. Caught by
# testing the negative case rather than assuming it.
data "aws_iam_policy_document" "bucket_for_cloudfront" {
  statement {
    sid     = "AllowCloudFrontReadPublishedObjectsOnly"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/index.html",
      "${aws_s3_bucket.data.arn}/us-states.json",
      "${aws_s3_bucket.data.arn}/results/*",
      "${aws_s3_bucket.data.arn}/basemap/*",
    ]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.data.id
  policy = data.aws_iam_policy_document.bucket_for_cloudfront.json
}

output "site_url" {
  value = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}
