"""Tests for EdgeTypeMatrix validation — TypeClass enum, TypeClassifier, ExtractionSchema.is_valid()."""

from __future__ import annotations

from context_service.extraction.models import ExtractionSchema, RelationshipType
from context_service.extraction.type_classifier import TypeClass, TypeClassifier

# ---------------------------------------------------------------------------
# TypeClass enum
# ---------------------------------------------------------------------------


class TestTypeClassEnum:
    def test_has_six_values(self) -> None:
        assert len(TypeClass) == 6

    def test_agent_value(self) -> None:
        assert TypeClass.AGENT == "Agent"

    def test_organization_value(self) -> None:
        assert TypeClass.ORGANIZATION == "Organization"

    def test_artifact_value(self) -> None:
        assert TypeClass.ARTIFACT == "Artifact"

    def test_concept_value(self) -> None:
        assert TypeClass.CONCEPT == "Concept"

    def test_event_value(self) -> None:
        assert TypeClass.EVENT == "Event"

    def test_location_value(self) -> None:
        assert TypeClass.LOCATION == "Location"

    def test_is_strenum(self) -> None:
        from enum import StrEnum

        assert issubclass(TypeClass, StrEnum)


# ---------------------------------------------------------------------------
# TypeClassifier.classify()
# ---------------------------------------------------------------------------


class TestTypeClassifierClassify:
    def setup_method(self) -> None:
        self.clf = TypeClassifier()

    def test_person_maps_to_agent(self) -> None:
        assert self.clf.classify("person") == TypeClass.AGENT

    def test_user_maps_to_agent(self) -> None:
        assert self.clf.classify("user") == TypeClass.AGENT

    def test_bot_maps_to_agent(self) -> None:
        assert self.clf.classify("bot") == TypeClass.AGENT

    def test_engineer_maps_to_agent(self) -> None:
        assert self.clf.classify("engineer") == TypeClass.AGENT

    def test_company_maps_to_organization(self) -> None:
        assert self.clf.classify("company") == TypeClass.ORGANIZATION

    def test_department_maps_to_organization(self) -> None:
        assert self.clf.classify("department") == TypeClass.ORGANIZATION

    def test_startup_maps_to_organization(self) -> None:
        assert self.clf.classify("startup") == TypeClass.ORGANIZATION

    def test_document_maps_to_artifact(self) -> None:
        assert self.clf.classify("document") == TypeClass.ARTIFACT

    def test_file_maps_to_artifact(self) -> None:
        assert self.clf.classify("file") == TypeClass.ARTIFACT

    def test_module_maps_to_artifact(self) -> None:
        assert self.clf.classify("module") == TypeClass.ARTIFACT

    def test_api_maps_to_artifact(self) -> None:
        assert self.clf.classify("api") == TypeClass.ARTIFACT

    def test_topic_maps_to_concept(self) -> None:
        assert self.clf.classify("topic") == TypeClass.CONCEPT

    def test_idea_maps_to_concept(self) -> None:
        assert self.clf.classify("idea") == TypeClass.CONCEPT

    def test_goal_maps_to_concept(self) -> None:
        assert self.clf.classify("goal") == TypeClass.CONCEPT

    def test_meeting_maps_to_event(self) -> None:
        assert self.clf.classify("meeting") == TypeClass.EVENT

    def test_deployment_maps_to_event(self) -> None:
        assert self.clf.classify("deployment") == TypeClass.EVENT

    def test_incident_maps_to_event(self) -> None:
        assert self.clf.classify("incident") == TypeClass.EVENT

    def test_city_maps_to_location(self) -> None:
        assert self.clf.classify("city") == TypeClass.LOCATION

    def test_country_maps_to_location(self) -> None:
        assert self.clf.classify("country") == TypeClass.LOCATION

    def test_unknown_type_returns_none(self) -> None:
        assert self.clf.classify("xyzzy_unknown_type_12345") is None

    def test_empty_string_returns_none(self) -> None:
        assert self.clf.classify("") is None

    def test_case_insensitive(self) -> None:
        assert self.clf.classify("Person") == TypeClass.AGENT
        assert self.clf.classify("COMPANY") == TypeClass.ORGANIZATION


# ---------------------------------------------------------------------------
# TypeClassifier.classify_batch()
# ---------------------------------------------------------------------------


class TestTypeClassifierClassifyBatch:
    def setup_method(self) -> None:
        self.clf = TypeClassifier()

    def test_batch_returns_list_same_length(self) -> None:
        types = ["person", "company", "document"]
        result = self.clf.classify_batch(types)
        assert len(result) == len(types)

    def test_batch_correct_values(self) -> None:
        types = ["person", "company", "document"]
        result = self.clf.classify_batch(types)
        assert result[0] == TypeClass.AGENT
        assert result[1] == TypeClass.ORGANIZATION
        assert result[2] == TypeClass.ARTIFACT

    def test_batch_empty_list(self) -> None:
        assert self.clf.classify_batch([]) == []

    def test_batch_unknown_returns_none(self) -> None:
        result = self.clf.classify_batch(["person", "xyzzy_unknown"])
        assert result[0] == TypeClass.AGENT
        assert result[1] is None


# ---------------------------------------------------------------------------
# ExtractionSchema.is_valid() — matrix enforcement
# ---------------------------------------------------------------------------


class TestExtractionSchemaIsValid:
    def test_empty_source_type_fails(self) -> None:
        assert not ExtractionSchema.is_valid("", RelationshipType.REFERENCES, "person")

    def test_empty_target_type_fails(self) -> None:
        assert not ExtractionSchema.is_valid("person", RelationshipType.REFERENCES, "")

    def test_invalid_edge_label_fails(self) -> None:
        assert not ExtractionSchema.is_valid("person", "NOT_A_LABEL", "company")  # type: ignore[arg-type]

    # COMPOSES: ANY -> Artifact, Organization
    def test_composes_person_to_document_valid(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.COMPOSES, "document")

    def test_composes_person_to_company_valid(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.COMPOSES, "company")

    def test_composes_any_to_person_invalid(self) -> None:
        assert not ExtractionSchema.is_valid("document", RelationshipType.COMPOSES, "person")

    def test_composes_any_to_topic_invalid(self) -> None:
        assert not ExtractionSchema.is_valid("person", RelationshipType.COMPOSES, "topic")

    # DEPENDS_ON: Artifact, Concept -> Artifact, Concept
    def test_depends_on_artifact_to_artifact_valid(self) -> None:
        assert ExtractionSchema.is_valid("module", RelationshipType.DEPENDS_ON, "api")

    def test_depends_on_concept_to_concept_valid(self) -> None:
        assert ExtractionSchema.is_valid("goal", RelationshipType.DEPENDS_ON, "idea")

    def test_depends_on_person_to_artifact_invalid(self) -> None:
        assert not ExtractionSchema.is_valid("person", RelationshipType.DEPENDS_ON, "module")

    # INSTANTIATES: ANY -> Concept
    def test_instantiates_any_to_concept_valid(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.INSTANTIATES, "goal")

    def test_instantiates_any_to_artifact_invalid(self) -> None:
        assert not ExtractionSchema.is_valid("person", RelationshipType.INSTANTIATES, "document")

    # CAUSES: Event, Agent -> ANY
    def test_causes_event_to_any_valid(self) -> None:
        assert ExtractionSchema.is_valid("incident", RelationshipType.CAUSES, "document")

    def test_causes_agent_to_any_valid(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.CAUSES, "meeting")

    def test_causes_artifact_to_any_invalid(self) -> None:
        assert not ExtractionSchema.is_valid("document", RelationshipType.CAUSES, "meeting")

    # PREVENTS: Agent, Artifact, Concept -> Event, Concept
    def test_prevents_agent_to_event_valid(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.PREVENTS, "incident")

    def test_prevents_artifact_to_concept_valid(self) -> None:
        assert ExtractionSchema.is_valid("document", RelationshipType.PREVENTS, "goal")

    def test_prevents_event_to_event_invalid(self) -> None:
        assert not ExtractionSchema.is_valid("incident", RelationshipType.PREVENTS, "meeting")

    # DERIVES_FROM, SPECIALIZES, CORROBORATES, CONTRADICTS, REFERENCES, RELATED_TO: ANY->ANY
    def test_derives_from_any_to_any_valid(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.DERIVES_FROM, "document")

    def test_related_to_any_to_any_valid(self) -> None:
        assert ExtractionSchema.is_valid("city", RelationshipType.RELATED_TO, "company")
