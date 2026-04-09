def tool_pasteappend(
        self,
        file: Optional[str] = None,
        initial_content: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = self._resolve_file(file)
        if not target:
            return "Paste append failed - no file specified"

        try:
            old_text = self._safe_existing_text(target)
        except ValueError as e:
            return str(e)

        checkpoint_note = self._maybe_checkpoint_before_edit(op="pasteappend", file=file)

        content = self._collect_multiline_input(initial_content=initial_content)
        updated = old_text + content
        result = self._apply_change_with_preview(target, updated)
        if result.startswith("Change applied"):
            commit_note = self._maybe_commit_after_edit(op="pasteappend", file=file)
            prefix_parts = []
            if checkpoint_note:
                prefix_parts.append(checkpoint_note)
            if commit_note:
                prefix_parts.append(commit_note)
            prefix = ("\n".join(prefix_parts) + "\n") if prefix_parts else ""
            return f"{prefix}{result} Appended pasted content to {target}"
        return result