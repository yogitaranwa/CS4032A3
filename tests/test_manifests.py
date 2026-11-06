from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return list(yaml.safe_load_all((ROOT / path).read_text()))


def test_namespaces_exist():
    names = {d["metadata"]["name"] for d in load("k8s/00-namespaces.yaml")}
    assert names == {"data", "pipeline", "app"}


def test_deployment_spec():
    d = load("k8s/app/deployment.yaml")[0]
    assert d["metadata"]["namespace"] == "app" and d["spec"]["replicas"] == 2
    c = d["spec"]["template"]["spec"]["containers"][0]
    assert {"cpu", "memory"} <= set(c["resources"]["requests"]) and {"cpu", "memory"} <= set(c["resources"]["limits"])
    assert c["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert c["readinessProbe"]["httpGet"]["path"] == "/readyz"
    env = {e["name"]: e for e in c["env"]}
    for name in ("MODEL_URI", "MODEL_VERSION", "S3_ENDPOINT", "MAX_NEW_TOKENS", "FAULT_INJECT"):
        assert name in env
    # credentials only through a Secret, never as literal values
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        assert "secretKeyRef" in env[name]["valueFrom"] and "value" not in env[name]
    assert d["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0


def test_hpa_and_ingress_and_service():
    h = load("k8s/app/hpa.yaml")[0]["spec"]
    assert (h["minReplicas"], h["maxReplicas"]) == (1, 2)
    assert h["metrics"][0]["resource"]["target"]["averageUtilization"] == 70
    ing = load("k8s/app/ingress.yaml")[0]
    assert ing["metadata"]["namespace"] == "app"
    assert ing["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/parse"
    svc = load("k8s/app/service.yaml")[0]
    assert svc["metadata"]["namespace"] == "app"


def test_seaweedfs_in_data_namespace_without_credentials():
    text = (ROOT / "k8s/data/seaweedfs.yaml").read_text()
    docs = list(yaml.safe_load_all(text))
    assert all(d["metadata"]["namespace"] == "data" for d in docs)
    assert "accessKey" not in text and "secretKey" not in text


def test_k3d_config():
    cfg = load("cluster/k3d.yaml")[0]
    assert cfg["kind"] == "Simple" and any("8080:80" in p["port"] for p in cfg["ports"])


def test_worker_job_in_pipeline_namespace():
    text = (ROOT / "k8s/pipeline/worker-job.yaml").read_text()
    assert "namespace: pipeline" in text and "SHARD_INDEX" in text and "SHARD_COUNT" in text


def test_dockerfile_pins_and_no_weights():
    text = (ROOT / "service/Dockerfile").read_text()
    assert "FROM python:3.11.9" in text and "safetensors" not in text
    for line in (ROOT / "service/requirements.txt").read_text().splitlines():
        if line and not line.startswith("--"):
            assert "==" in line, line
    for line in (ROOT / "training/requirements.txt").read_text().splitlines():
        if line and not line.startswith("--"):
            assert "==" in line, line


def test_graceful_termination():
    d = load("k8s/app/deployment.yaml")[0]["spec"]["template"]["spec"]
    assert d["terminationGracePeriodSeconds"] >= 20
    assert "preStop" in d["containers"][0]["lifecycle"]
