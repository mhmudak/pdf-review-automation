"""Guard against accidentally deploying the HTTP server as a Cloud Run Job."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dedicated_job_image_runs_one_shot_entrypoint():
    content = (ROOT / 'Dockerfile.job').read_text(encoding='utf-8')
    assert 'ENTRYPOINT ["python", "job_runner.py"]' in content
    assert 'COPY src/ ./' in content
    assert 'gunicorn' not in content.lower()


def test_cloud_build_only_builds_and_pushes():
    content = (ROOT / 'cloudbuild.job.yaml').read_text(encoding='utf-8')
    assert 'Dockerfile.job' in content
    assert '${_IMAGE}' in content
    assert 'gcloud run' not in content
    assert 'scheduler jobs' not in content


def test_original_http_dockerfile_unmodified():
    content = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert 'http_service:app' in content
