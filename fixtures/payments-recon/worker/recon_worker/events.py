"""Pub/Sub integration: publish run results, consume statement uploads."""

import json
import os

from google.cloud import pubsub_v1

RUN_EVENTS_TOPIC = os.environ.get("RECON_EVENTS_TOPIC", "projects/demo/topics/recon-events")
UPLOADS_SUBSCRIPTION = os.environ["RECON_UPLOADS_SUBSCRIPTION"]

publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()


def publish_run_completed(run_id: str, matched: int) -> None:
    # ad2v: REQ-005
    payload = json.dumps({"run_id": run_id, "matched": matched}).encode("utf-8")
    publisher.publish(RUN_EVENTS_TOPIC, payload)


def handle_statement_uploaded(message) -> None:
    from recon_worker.jobs import run_nightly

    transactions = json.loads(message.data)["transactions"]
    run_nightly(transactions)
    message.ack()


def listen() -> None:
    future = subscriber.subscribe(UPLOADS_SUBSCRIPTION, callback=handle_statement_uploaded)
    future.result()
