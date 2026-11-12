"""Attack registration for models AgentDojo does not know by name.

``important_instructions`` calls ``get_model_name_from_pipeline`` (agentdojo/attacks/base_attacks.py), which
raises unless the pipeline name contains a key of ``MODEL_NAMES``. We register the *same template* under the
same name with the prose model name derived from our pipeline name, so attack strength is unchanged and
comparable. The prose name used is written into every result file (ADR-003).
"""

from __future__ import annotations

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.attacks.attack_registry import register_attack
from agentdojo.attacks.important_instructions_attacks import ImportantInstructionsAttack
from agentdojo.functions_runtime import Env
from agentdojo.task_suite.task_suite import TaskSuite

PROSE_NAMES: dict[str, str] = {
    "llama": "Llama",
    "gpt-oss": "GPT",
    "gpt": "GPT",
    "qwen": "Qwen",
    "gemini": "AI model developed by Google",
    "gemma": "AI model developed by Google",
    "mistral": "Mistral",
    "mixtral": "Mixtral",
    "claude": "Claude",
}
DEFAULT_PROSE_NAME = "the AI language model"


def prose_model_name(pipeline_name: str | None) -> str:
    lowered = (pipeline_name or "").lower()
    for needle, prose in PROSE_NAMES.items():
        if needle in lowered:
            return prose
    return DEFAULT_PROSE_NAME


@register_attack
class ImportantInstructionsAttackNamed(ImportantInstructionsAttack):
    """``important_instructions`` with the victim model's prose name taken from our pipeline name."""

    name = "important_instructions"

    def __init__(self, task_suite: TaskSuite[Env], target_pipeline: BasePipelineElement) -> None:
        # Skip ImportantInstructionsAttack.__init__ (it would raise on unknown names); replicate its effect.
        super(ImportantInstructionsAttack, self).__init__(self._JB_STRING, task_suite, target_pipeline)
        self.user_name = "Emma Johnson"
        self.model_name = prose_model_name(target_pipeline.name)
