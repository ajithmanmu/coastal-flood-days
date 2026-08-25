###############################################################################
# Push-to-deploy
#
# GitHub Actions assumes a role via OIDC. No access keys are stored anywhere --
# GitHub presents a short-lived signed token and AWS exchanges it for temporary
# credentials. This repository is public, so a long-lived key in a repo secret
# would be one bad workflow edit away from being printed to a public log.
#
# The trust policy pins the exact repo AND the exact branch. Without the `sub`
# condition any GitHub Actions workflow in the world could assume this role.
###############################################################################

variable "github_repo" {
  description = "owner/name of the repository allowed to deploy"
  type        = string
  default     = "ajithmanmu/coastal-flood-days"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # AWS stopped validating these for providers backed by a well-known CA, but the
  # argument is still required. Both of GitHub's published values are listed so a
  # rotation does not break the provider.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only pushes to main. Pull requests -- including from forks on a public repo --
    # produce a different `sub` and cannot assume this role.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "coastal-flood-days-github-deploy"
  description        = "Publishes the page and its vendored assets. Cannot touch raw/ or results/."
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600
}

# Deliberately narrow. CI publishes the page and its assets and nothing else -- it has no
# reason to write the dataset, and no way to delete anything. The daily Lambda owns
# results/, the backfill owns raw/, and neither is reachable from here.
data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid     = "PublishPageAndAssets"
    actions = ["s3:PutObject", "s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/index.html",
      "${aws_s3_bucket.data.arn}/vendor/*",
    ]
  }

  # `aws s3 sync` lists the destination before copying. Scoped by prefix so CI cannot
  # enumerate the raw archive.
  statement {
    sid       = "ListVendorPrefixOnly"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["vendor/*", "vendor", ""]
    }
  }

  statement {
    sid       = "InvalidateEdgeCache"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [aws_cloudfront_distribution.site.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "publish-page"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

output "github_deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}
