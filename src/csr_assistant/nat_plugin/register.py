"""NeMo Agent Toolkit plugin: `csr_review` takes "draft_path | tables_dir | synopsis_path" and returns the report."""

from __future__ import annotations

from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig


class CSRReviewConfig(FunctionBaseConfig, name="csr_review"):
    llm_name: LLMRef
    fast_llm_name: LLMRef | None = None
    max_revisions: int = 1


@register_function(config_type=CSRReviewConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def csr_review(config: CSRReviewConfig, builder: Builder):
    from ..agent import Options, run
    from ..llm import LangChainAdapter

    reasoning = await builder.get_llm(config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    fast = (
        await builder.get_llm(config.fast_llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
        if config.fast_llm_name
        else reasoning
    )
    llm = LangChainAdapter(reasoning, fast)

    async def _run(request: str) -> str:
        """Review a clinical study report draft against ICH E3 and its source tables.
        Input: 'draft.md | tables_folder | synopsis.md'."""
        parts = [p.strip() for p in request.split("|")]
        state = await run(
            {"draft": parts[0], "tables": parts[1], "synopsis": parts[2] if len(parts) > 2 else None},
            llm,
            Options(max_revisions=config.max_revisions),
        )
        return state["report_md"]

    yield FunctionInfo.from_fn(_run, description=_run.__doc__)
