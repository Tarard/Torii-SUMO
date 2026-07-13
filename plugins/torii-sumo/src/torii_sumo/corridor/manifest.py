from __future__ import annotations

from datetime import datetime

from pydantic import model_validator

from .base import ContractModel, Sha256, StableToken
from .candidates import CandidateGraph, Hypothesis
from .enums import ArtifactRole, GateStatus
from .evidence import EvidenceRecord, Finding, InvariantResult
from .ids import require_stable_id
from .review import ReviewCase, ReviewDecision, ReviewTask
from .scope import ScopeSpec
from .toolchain import ToolchainLock
from .workflow import NetworkQualityVectorV1, StageOutcome, WorkflowExecution


class ArtifactIdentity(ContractModel):
    artifact_schema: str
    artifact_id: StableToken
    role: ArtifactRole
    path: str
    sha256: Sha256
    producer: str
    toolchain_id: StableToken

    @model_validator(mode="after")
    def validate_artifact(self) -> ArtifactIdentity:
        require_stable_id(self.artifact_id, kind="artifact")
        require_stable_id(self.toolchain_id, kind="toolchain")
        if not self.path:
            raise ValueError("Artifacts require a path.")
        return self


class ArtifactDependency(ContractModel):
    parent_artifact_id: StableToken
    child_artifact_id: StableToken
    relation: str

    @model_validator(mode="after")
    def validate_dependency(self) -> ArtifactDependency:
        require_stable_id(self.parent_artifact_id, kind="artifact")
        require_stable_id(self.child_artifact_id, kind="artifact")
        if self.parent_artifact_id == self.child_artifact_id:
            raise ValueError("Artifact dependencies cannot be self-referential.")
        return self


class ArtifactManifestV1(ContractModel):
    schema_id: str = "torii.corridor.artifact-manifest/v1"
    manifest_id: StableToken
    created_at: datetime
    toolchain_id: StableToken
    source_artifact_id: StableToken
    candidate_artifact_ids: tuple[StableToken, ...] = ()
    artifacts: tuple[ArtifactIdentity, ...]
    dependencies: tuple[ArtifactDependency, ...] = ()
    gate_trace: dict[str, GateStatus]
    source_mutated: bool = False

    @model_validator(mode="after")
    def validate_manifest(self) -> ArtifactManifestV1:
        require_stable_id(self.manifest_id, kind="manifest")
        require_stable_id(self.toolchain_id, kind="toolchain")
        require_stable_id(self.source_artifact_id, kind="artifact")
        if self.created_at.tzinfo is None:
            raise ValueError("Artifact manifests require a timezone-aware created_at.")
        artifacts_by_id = {artifact.artifact_id: artifact for artifact in self.artifacts}
        if len(artifacts_by_id) != len(self.artifacts):
            raise ValueError("Artifact IDs must be unique.")
        if len({artifact.path for artifact in self.artifacts}) != len(self.artifacts):
            raise ValueError("Artifact paths must be unique.")
        if self.source_artifact_id not in artifacts_by_id:
            raise ValueError("Manifest source artifact is missing.")
        source = artifacts_by_id[self.source_artifact_id]
        if source.role is not ArtifactRole.SOURCE_NET:
            raise ValueError("Manifest source_artifact_id must reference a source-net.")
        for candidate_id in self.candidate_artifact_ids:
            require_stable_id(candidate_id, kind="artifact")
            candidate = artifacts_by_id.get(candidate_id)
            if candidate is None or candidate.role is not ArtifactRole.CANDIDATE_NET:
                raise ValueError("Candidate artifact references must resolve to candidate-net artifacts.")
            if candidate.path == source.path or candidate.sha256 == source.sha256:
                raise ValueError("Source and candidate artifacts must have distinct paths and hashes.")
        for dependency in self.dependencies:
            if (
                dependency.parent_artifact_id not in artifacts_by_id
                or dependency.child_artifact_id not in artifacts_by_id
            ):
                raise ValueError("Artifact dependency references are not closed.")
        if self.source_mutated:
            raise ValueError("A corridor research manifest can never certify source mutation.")
        return self


class CorridorResearchBundle(ContractModel):
    """Aggregate schema root for every frozen stage-0 contract."""

    schema_id: str = "torii.corridor.research-bundle/v1"
    toolchain: ToolchainLock
    scope: ScopeSpec
    evidence: tuple[EvidenceRecord, ...] = ()
    findings: tuple[Finding, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    candidates: CandidateGraph
    invariants: tuple[InvariantResult, ...] = ()
    quality: NetworkQualityVectorV1
    stage_outcomes: tuple[StageOutcome, ...] = ()
    workflow: WorkflowExecution
    review_tasks: tuple[ReviewTask, ...] = ()
    review_cases: tuple[ReviewCase, ...] = ()
    review_decisions: tuple[ReviewDecision, ...] = ()
    artifact_manifest: ArtifactManifestV1
