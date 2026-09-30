# Least-privilege access for the Bedrock explanation

The app makes one kind of AWS call: `bedrock-runtime` Converse to Amazon Nova Pro through the APAC cross-region inference profile. Converse needs `bedrock:InvokeModel`. `scripts/check_bedrock.py` also reads the profile or model details, and calls `sts:GetCallerIdentity`, which needs no permission. [`bedrock-invoke-policy.json`](bedrock-invoke-policy.json) allows exactly that and nothing else.

A cross-region inference profile can route a request to another APAC region, so the policy allows the Nova Pro foundation model in every region (`arn:aws:bedrock:*::foundation-model/...`) as well as the profile itself, following the AWS guidance for inference profiles. Change `ap-southeast-1` in the profile ARN if you run the app from another region.

## Set it up

Run these as an administrator of the account, from the repo root. The new secret key is printed once, straight into your terminal, so keep it out of the repo, chats and screenshots.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/ACCOUNT_ID/$ACCOUNT_ID/" docs/aws/bedrock-invoke-policy.json > /tmp/attackgraph-bedrock-policy.json
aws iam create-user --user-name attackgraph-bedrock
aws iam put-user-policy --user-name attackgraph-bedrock --policy-name attackgraph-bedrock-invoke --policy-document file:///tmp/attackgraph-bedrock-policy.json
aws iam create-access-key --user-name attackgraph-bedrock
aws configure --profile attackgraph
```

At the `aws configure` prompts, paste the new access key ID and secret, and use `ap-southeast-1` as the region. Then check access without any charge, and run the app with the profile:

```bash
AWS_PROFILE=attackgraph .venv/bin/python scripts/check_bedrock.py
AWS_PROFILE=attackgraph .venv/bin/streamlit run app.py
```

The check should print the model, the region, an IAM user as the caller, and the profile as `ACTIVE`, with no root-key warning.

## Retire root access keys

Root-user access keys should not exist for day-to-day use. Once the check passes with the new profile, sign in as the root user and open **Security credentials** in the AWS console. Deactivate the root access key, confirm the app still works with `AWS_PROFILE=attackgraph`, then delete it.
