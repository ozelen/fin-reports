import {
  Box,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  OutlinedInput,
  Select,
} from "@mui/material";

export default function TagMultiSelect({
  tags,
  value,
  onChange,
  label = "Tags",
  size = "small",
  fullWidth = true,
}) {
  const byId = Object.fromEntries(tags.map((t) => [t.id, t]));
  return (
    <FormControl size={size} fullWidth={fullWidth}>
      <InputLabel>{label}</InputLabel>
      <Select
        multiple
        value={value}
        onChange={(e) =>
          onChange(
            typeof e.target.value === "string"
              ? e.target.value.split(",").map(Number)
              : e.target.value,
          )
        }
        input={<OutlinedInput label={label} />}
        renderValue={(selected) => (
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
            {selected.map((id) => (
              <Chip
                key={id}
                size="small"
                label={byId[id]?.name || id}
                sx={{ bgcolor: byId[id]?.color, color: "#fff" }}
              />
            ))}
          </Box>
        )}
      >
        {tags.map((t) => (
          <MenuItem key={t.id} value={t.id}>
            <Box
              component="span"
              sx={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                bgcolor: t.color,
                mr: 1,
                display: "inline-block",
              }}
            />
            {t.name}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
