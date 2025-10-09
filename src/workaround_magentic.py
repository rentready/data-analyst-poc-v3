"""
Temporary workaround for Magentic One deadlock issue.
Use this in your application until the library is updated.
"""

import logging
from typing import Any
from agent_framework._workflows._magentic import MagenticOrchestratorExecutor
from agent_framework._workflows._workflow_context import WorkflowContext
from agent_framework._workflows._magentic import (
    MagenticResponseMessage,
    MagenticRequestMessage,
)

logger = logging.getLogger(__name__)


def patch_magentic_orchestrator():
    """Apply monkey patch to fix deadlock in reset_and_replan."""
    
    # Save original method references
    _original_run_inner_loop = MagenticOrchestratorExecutor._run_inner_loop
    _original_run_inner_loop_locked = MagenticOrchestratorExecutor._run_inner_loop_locked
    _original_init = MagenticOrchestratorExecutor.__init__
    
    # Patched __init__ to add _needs_reset flag
    def _patched_init(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        self._needs_reset = False
    
    # Patched _run_inner_loop to check reset flag AFTER releasing lock
    async def _patched_run_inner_loop(
        self,
        context: WorkflowContext[MagenticResponseMessage | MagenticRequestMessage, Any],
    ) -> None:
        logger.info("Magentic Orchestrator: Running inner loop")
        """Run the inner orchestration loop. Coordination phase. Serialized with a lock."""
        if self._context is None or self._task_ledger is None:
            raise RuntimeError("Context or task ledger not initialized")
        
        # Execute locked portion
        async with self._inner_loop_lock:
            await _original_run_inner_loop_locked(self, context)
        
        # Check for reset AFTER releasing the lock - this prevents deadlock
        if getattr(self, '_needs_reset', False):
            self._needs_reset = False
            logger.debug("Magentic Orchestrator: Executing deferred reset_and_replan")
            await self._reset_and_replan(context)
    
    # Patched _run_inner_loop_locked to set flag instead of direct call
    async def _patched_run_inner_loop_locked(
        self,
        context: WorkflowContext[MagenticResponseMessage | MagenticRequestMessage, Any],
    ) -> None:
        """Run inner loop with exclusive access."""
        ctx = self._context
        if ctx is None:
            raise RuntimeError("Context not initialized")
        
        # Check limits first
        within_limits = await self._check_within_limits_or_complete(context)
        if not within_limits:
            return

        ctx.round_count += 1
        logger.info("Magentic Orchestrator: Inner loop - round %s", ctx.round_count)

        # Create progress ledger using the manager
        try:
            current_progress_ledger = await self._manager.create_progress_ledger(ctx.clone(deep=True))
        except Exception as ex:
            logger.warning("Magentic Orchestrator: Progress ledger creation failed, triggering reset: %s", ex)
            # Set flag instead of direct call to avoid deadlock
            self._needs_reset = True
            return

        logger.debug(
            "Progress evaluation: satisfied=%s, next=%s",
            current_progress_ledger.is_request_satisfied.answer,
            current_progress_ledger.next_speaker.answer,
        )

        # Check for task completion
        if current_progress_ledger.is_request_satisfied.answer:
            logger.info("Magentic Orchestrator: Task completed")
            await self._prepare_final_answer(context)
            return

        # Check for stalling or looping
        if not current_progress_ledger.is_progress_being_made.answer or current_progress_ledger.is_in_loop.answer:
            ctx.stall_count += 1
        else:
            ctx.stall_count = max(0, ctx.stall_count - 1)

        if ctx.stall_count > self._manager.max_stall_count:
            logger.info("Magentic Orchestrator: Stalling detected. Resetting and replanning")
            # Set flag instead of direct call to avoid deadlock
            self._needs_reset = True
            return

        # Determine the next speaker and instruction
        answer_val = current_progress_ledger.next_speaker.answer
        if not isinstance(answer_val, str):
            logger.warning("Next speaker answer was not a string; selecting first participant as fallback")
            answer_val = next(iter(self._participants.keys()))
        next_speaker_value: str = answer_val
        instruction = current_progress_ledger.instruction_or_question.answer

        if next_speaker_value not in self._participants:
            logger.warning("Invalid next speaker: %s", next_speaker_value)
            await self._prepare_final_answer(context)
            return

        # Add instruction to conversation (assistant guidance)
        from agent_framework import ChatMessage, Role
        from agent_framework._workflows._magentic import MAGENTIC_MANAGER_NAME
        
        instruction_msg = ChatMessage(
            role=Role.ASSISTANT,
            text=str(instruction),
            author_name=MAGENTIC_MANAGER_NAME,
        )
        ctx.chat_history.append(instruction_msg)
        
        # Surface instruction message to observers
        if self._message_callback:
            import contextlib
            from agent_framework._workflows._magentic import ORCH_MSG_KIND_INSTRUCTION
            with contextlib.suppress(Exception):
                await self._message_callback(self.id, instruction_msg, ORCH_MSG_KIND_INSTRUCTION)

        # Determine the selected agent's executor id
        target_executor_id = f"agent_{next_speaker_value}"

        # Request specific agent to respond
        from agent_framework._workflows._magentic import MagenticRequestMessage
        logger.debug("Magentic Orchestrator: Requesting %s to respond", next_speaker_value)
        await context.send_message(
            MagenticRequestMessage(
                agent_name=next_speaker_value,
                instruction=str(instruction),
                task_context=ctx.task.text,
            ),
            target_id=target_executor_id,
        )
    
    # Apply the patches
    MagenticOrchestratorExecutor.__init__ = _patched_init
    MagenticOrchestratorExecutor._run_inner_loop = _patched_run_inner_loop
    MagenticOrchestratorExecutor._run_inner_loop_locked = _patched_run_inner_loop_locked
    
    logger.info("✓ Applied Magentic Orchestrator deadlock fix")
    print("✓ Applied Magentic Orchestrator deadlock fix")