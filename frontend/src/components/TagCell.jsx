import { Box, Chip, IconButton, Popover, Stack } from "@mui/material";
import { styled } from "@mui/material/styles";
import useAutocomplete from "@mui/material/useAutocomplete";
import AddIcon from "@mui/icons-material/Add";
import { useState } from "react";

const InputWrapper = styled("div")(({ theme }) => ({
  "& input": {
    width: "100%",
    boxSizing: "border-box",
    padding: "6px 10px",
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: theme.shape.borderRadius,
    fontSize: 14,
    fontFamily: "inherit",
    outline: "none",
  },
  "& input:focus": {
    border: `1px solid ${theme.palette.primary.main}`,
  },
}));

const Listbox = styled("ul")(({ theme }) => ({
  margin: 0,
  padding: "4px 0 0",
  listStyle: "none",
  maxHeight: 260,
  overflow: "auto",
  "& li": {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px 12px",
    cursor: "pointer",
    fontSize: 14,
  },
  "& li.Mui-focused, & li[aria-selected='true']": {
    backgroundColor: theme.palette.action.hover,
  },
}));

/**
 * In-row tag display: the row's tags as deletable chips plus a "+" button that
 * asks the parent to open the shared editor popover anchored to this button.
 * The editor state is held by the parent (TagEditorPopover) so it survives
 * DataGrid cell re-renders.
 */
export function TagCell({ row, onOpen, onRemove }) {
  const rowTags = row.tags || [];
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" sx={{ flexWrap: "wrap", py: 0.5 }}>
      {rowTags.map((t) => (
        <Chip
          key={t.id}
          size="small"
          label={t.name}
          title={`source: ${t.source}`}
          onDelete={(e) => {
            e.stopPropagation();
            onRemove(row, t.id);
          }}
          sx={{
            bgcolor: t.color,
            color: "#fff",
            "& .MuiChip-deleteIcon": { color: "rgba(255,255,255,0.7)" },
            "& .MuiChip-deleteIcon:hover": { color: "#fff" },
          }}
        />
      ))}
      <IconButton
        size="small"
        onClick={(e) => {
          e.stopPropagation();
          onOpen(e.currentTarget, row);
        }}
        sx={{ border: "1px dashed", borderColor: "divider", width: 22, height: 22 }}
      >
        <AddIcon sx={{ fontSize: 16 }} />
      </IconButton>
    </Stack>
  );
}

/**
 * Shared popover with a single typeahead panel (input + results in one surface)
 * to add an existing tag or create a new one on the spot. Rendered once at the
 * page level and anchored to whichever row's "+" button was clicked.
 *
 * Built on `useAutocomplete` so the text field and option list live in the same
 * Popover paper instead of two disconnected floating panels.
 */
export function TagEditorPopover({
  anchorEl,
  row,
  allTags,
  onClose,
  onAddExisting,
  onCreateAndAdd,
}) {
  const open = Boolean(anchorEl) && Boolean(row);
  return (
    <Popover
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
      slotProps={{ paper: { sx: { width: 260 } } }}
    >
      {open && (
        <TagEditorContent
          row={row}
          allTags={allTags}
          onClose={onClose}
          onAddExisting={onAddExisting}
          onCreateAndAdd={onCreateAndAdd}
        />
      )}
    </Popover>
  );
}

/**
 * The typeahead body. Mounted only while the popover is open so
 * `useAutocomplete`'s effects always have a live input element to bind to.
 */
function TagEditorContent({ row, allTags, onClose, onAddExisting, onCreateAndAdd }) {
  const [busy, setBusy] = useState(false);
  const applied = new Set((row.tags || []).map((t) => t.id));
  const options = allTags.filter((t) => !applied.has(t.id));

  const commit = async (val) => {
    if (!val || busy) return;
    setBusy(true);
    try {
      if (val.inputValue) {
        const name = val.inputValue.trim();
        if (name) await onCreateAndAdd(row, name);
      } else {
        await onAddExisting(row, val);
      }
    } finally {
      setBusy(false);
      onClose();
    }
  };

  const {
    getRootProps,
    getInputProps,
    getListboxProps,
    getOptionProps,
    groupedOptions,
  } = useAutocomplete({
    open: true,
    options,
    getOptionLabel: (o) => o.name,
    filterOptions: (opts, params) => {
      const input = params.inputValue.trim().toLowerCase();
      const filtered = opts.filter((o) => o.name.toLowerCase().includes(input));
      const exists = opts.some((o) => o.name.toLowerCase() === input);
      if (input && !exists) {
        filtered.push({
          inputValue: params.inputValue.trim(),
          name: `Create "${params.inputValue.trim()}"`,
        });
      }
      return filtered;
    },
    autoHighlight: true,
    clearOnBlur: false,
    selectOnFocus: true,
    handleHomeEndKeys: true,
    onChange: (_, val) => commit(val),
  });

  return (
    <>
      <Box {...getRootProps()} sx={{ p: 1 }}>
        <InputWrapper>
          <input {...getInputProps()} autoFocus placeholder="Add or create tag" />
        </InputWrapper>
      </Box>
      {groupedOptions.length > 0 && (
        <Listbox {...getListboxProps()}>
          {groupedOptions.map((option, index) => {
            const { key, ...optionProps } = getOptionProps({ option, index });
            return (
              <li key={key} {...optionProps}>
                {option.id != null ? (
                  <Box
                    component="span"
                    sx={{
                      width: 12,
                      height: 12,
                      borderRadius: "50%",
                      bgcolor: option.color,
                      flexShrink: 0,
                    }}
                  />
                ) : (
                  <AddIcon sx={{ fontSize: 16, color: "text.secondary" }} />
                )}
                {option.name}
              </li>
            );
          })}
        </Listbox>
      )}
    </>
  );
}

export default TagCell;
