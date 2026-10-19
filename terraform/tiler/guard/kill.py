"""Cost guard kill switch (guard.tf): stop the tiler and take its CloudFront
distributions offline.

Invoked by the kill alarm (CloudFront bytes downloaded far above normal) or,
through SNS, by the budget backstop. It sets the tiler Lambdas' reserved
concurrency to 0 (no more renders) and disables the distributions (no more
requests or transfer; ~5-15 min to take effect), then reports what it did to
the alert topic. `tofu apply` restores both.

    {"dry_run": true}   # check access and report, change nothing
"""

import json
import os

import boto3

FUNCTIONS = json.loads(os.environ["FUNCTIONS"])  # [{"name": ..., "region": ...}]
DISTRIBUTIONS = json.loads(os.environ["DISTRIBUTIONS"])  # [distribution id]
ALERT_TOPIC = os.environ.get("ALERT_TOPIC")


def reason(event) -> str:
    if isinstance(event, dict) and "alarmData" in event:
        return f"alarm {event['alarmData'].get('alarmName')}"
    if isinstance(event, dict) and event.get("Records"):
        return f"budget: {event['Records'][0].get('Sns', {}).get('Subject') or 'notification'}"
    return "manual invocation"


def handler(event, context):
    dry = isinstance(event, dict) and bool(event.get("dry_run"))
    done, errors = [], []

    for f in FUNCTIONS:
        try:
            lam = boto3.client("lambda", region_name=f["region"])
            if dry:
                current = lam.get_function_concurrency(FunctionName=f["name"]).get("ReservedConcurrentExecutions")
                done.append(f"would set {f['name']} ({f['region']}) reserved concurrency {current} -> 0")
            else:
                lam.put_function_concurrency(FunctionName=f["name"], ReservedConcurrentExecutions=0)
                done.append(f"set {f['name']} ({f['region']}) reserved concurrency to 0")
        except Exception as e:  # noqa: BLE001  (keep going: stop as much as possible; raised below)
            errors.append(f"{f['name']}: {e}")

    cf = boto3.client("cloudfront")
    for d in DISTRIBUTIONS:
        try:
            r = cf.get_distribution_config(Id=d)
            cfg = r["DistributionConfig"]
            if dry:
                done.append(f"would disable distribution {d} (enabled: {cfg['Enabled']})")
            elif cfg["Enabled"]:
                cfg["Enabled"] = False
                cf.update_distribution(Id=d, IfMatch=r["ETag"], DistributionConfig=cfg)
                done.append(f"disabled distribution {d}")
            else:
                done.append(f"distribution {d} already disabled")
        except Exception as e:  # noqa: BLE001  (raised below)
            errors.append(f"{d}: {e}")

    report = {"reason": reason(event), "dry_run": dry, "done": done, "errors": errors}
    print(json.dumps(report))
    if ALERT_TOPIC and not dry:
        boto3.client("sns").publish(
            TopicArn=ALERT_TOPIC,
            Subject="Cost guard: tiler stopped",
            Message=json.dumps(report, indent=1) + "\n\nRestore with `tofu apply` in the deployment's stack.",
        )
    if errors:
        raise RuntimeError(f"kill switch incomplete: {errors}")
    return report
