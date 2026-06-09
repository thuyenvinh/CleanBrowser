import { Plus, Search, Monitor, X, Play, Square, Maximize2, Workflow } from "lucide-react";
import { useMemo, useState } from "react";
import type { Profile } from "../lib/api";
import { StatusIndicator } from "./StatusIndicator";

interface ProfileListProps {
  profiles: Profile[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  /** Bulk callbacks — when undefined the toolbar collapses to read-only mode. */
  onBulkLaunch?: (profileIds: string[]) => void;
  onBulkStop?: (profileIds: string[]) => void;
  onBulkResize?: (profileIds: string[]) => void;
  onBulkRunAutomation?: (profileIds: string[]) => void;
}

export function ProfileList({
  profiles,
  selectedId,
  onSelect,
  onNew,
  onBulkLaunch,
  onBulkStop,
  onBulkResize,
  onBulkRunAutomation,
}: ProfileListProps) {
  // Multi-select state. Stored as a Set keyed by profile id so toggling
  // is O(1) and the selection survives re-renders triggered by status
  // polling. Ids that disappear (profile deleted out-of-band) are
  // implicitly cleaned up by intersecting with the current list at
  // toolbar-click time.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  // M12: filter by tags (multi-select) and region (single-select). These are
  // derived from the loaded profile list — we intentionally don't fetch them
  // separately so the dropdowns always match the data actually visible.
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [selectedRegion, setSelectedRegion] = useState<string>("");

  const allTags = useMemo(() => {
    const set = new Set<string>();
    profiles.forEach((p) => p.tags.forEach((t) => set.add(t.tag)));
    return Array.from(set).sort();
  }, [profiles]);

  const allRegions = useMemo(() => {
    const set = new Set<string>();
    profiles.forEach((p) => {
      if (p.region) set.add(p.region);
    });
    return Array.from(set).sort();
  }, [profiles]);

  const filtered = profiles.filter((p) => {
    if (search && !p.name.toLowerCase().includes(search.toLowerCase())) {
      return false;
    }
    if (selectedRegion && p.region !== selectedRegion) return false;
    if (selectedTags.length > 0) {
      const profileTagSet = new Set(p.tags.map((t) => t.tag));
      // Require ALL selected tags to be present (intersection semantics —
      // matches how users typically narrow down: "show me everything tagged
      // BOTH social AND scraping", not "either").
      if (!selectedTags.every((t) => profileTagSet.has(t))) return false;
    }
    return true;
  });

  const hasFilters =
    search !== "" || selectedTags.length > 0 || selectedRegion !== "";

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };

  const clearFilters = () => {
    setSearch("");
    setSelectedTags([]);
    setSelectedRegion("");
  };

  const runningCount = profiles.filter((p) => p.status === "running").length;

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const selectAllFiltered = () => {
    setSelected(new Set(filtered.map((p) => p.id)));
  };
  const clearSelection = () => setSelected(new Set());
  // Filter to ids that still exist in the current list, then pass to the
  // callback. Prevents stale ids leaking into the bulk request.
  const selectedIds = (): string[] => {
    const visibleIds = new Set(profiles.map((p) => p.id));
    return Array.from(selected).filter((id) => visibleIds.has(id));
  };
  const bulkEnabled = Boolean(
    onBulkLaunch || onBulkStop || onBulkResize || onBulkRunAutomation,
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2 mb-3">
          <Monitor className="h-4 w-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight">CloakBrowser Manager</h1>
        </div>
        {runningCount > 0 && (
          <div className="text-xs text-gray-500 mb-3">
            {runningCount} running
          </div>
        )}
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <input
            type="text"
            placeholder="Search profiles..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-8 py-1.5 text-xs"
          />
        </div>

        {/* M12: Region + tags filters. Only rendered when there's something
            to filter by — otherwise the sidebar stays compact for users with
            no metadata on their profiles yet. */}
        {(allRegions.length > 0 || allTags.length > 0) && (
          <div className="mt-2 space-y-2">
            {allRegions.length > 0 && (
              <select
                value={selectedRegion}
                onChange={(e) => setSelectedRegion(e.target.value)}
                className="input py-1 text-xs w-full"
              >
                <option value="">All regions</option>
                {allRegions.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            )}
            {allTags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {allTags.map((t) => {
                  const active = selectedTags.includes(t);
                  return (
                    <button
                      key={t}
                      type="button"
                      onClick={() => toggleTag(t)}
                      className={`text-[10px] px-1.5 py-0.5 rounded-full border transition-colors ${
                        active
                          ? "bg-accent/20 text-accent border-accent/40"
                          : "bg-surface-4 text-gray-400 border-transparent hover:border-border-hover"
                      }`}
                    >
                      {t}
                    </button>
                  );
                })}
              </div>
            )}
            {hasFilters && (
              <button
                type="button"
                onClick={clearFilters}
                className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-gray-300"
              >
                <X className="h-3 w-3" />
                Clear filters
              </button>
            )}
          </div>
        )}
      </div>

      {/* Bulk toolbar — only visible when at least one row is checked. */}
      {bulkEnabled && selected.size > 0 && (
        <div className="px-3 py-2 border-b border-border bg-surface-2 flex items-center gap-1.5 flex-wrap">
          <span className="text-xs text-gray-300 mr-1">
            {selected.size} selected
          </span>
          {onBulkLaunch && (
            <button
              type="button"
              onClick={() => onBulkLaunch(selectedIds())}
              title="Launch all selected"
              className="h-6 px-2 inline-flex items-center gap-1 rounded text-[11px] bg-emerald-600 hover:bg-emerald-500 text-white"
            >
              <Play className="h-3 w-3" /> Launch
            </button>
          )}
          {onBulkStop && (
            <button
              type="button"
              onClick={() => onBulkStop(selectedIds())}
              title="Stop all selected"
              className="h-6 px-2 inline-flex items-center gap-1 rounded text-[11px] bg-red-600 hover:bg-red-500 text-white"
            >
              <Square className="h-3 w-3" /> Stop
            </button>
          )}
          {onBulkResize && (
            <button
              type="button"
              onClick={() => onBulkResize(selectedIds())}
              title="Resize viewport on all selected"
              className="h-6 px-2 inline-flex items-center gap-1 rounded text-[11px] bg-surface-3 hover:bg-surface-4 text-gray-200"
            >
              <Maximize2 className="h-3 w-3" /> Resize
            </button>
          )}
          {onBulkRunAutomation && (
            <button
              type="button"
              onClick={() => onBulkRunAutomation(selectedIds())}
              title="Run an automation against all selected"
              className="h-6 px-2 inline-flex items-center gap-1 rounded text-[11px] bg-accent hover:bg-accent/80 text-white"
            >
              <Workflow className="h-3 w-3" /> Run
            </button>
          )}
          <div className="flex-1" />
          <button
            type="button"
            onClick={selectAllFiltered}
            className="text-[10px] text-gray-400 hover:text-gray-200"
          >
            Select all ({filtered.length})
          </button>
          <button
            type="button"
            onClick={clearSelection}
            className="text-[10px] text-gray-400 hover:text-gray-200 ml-2"
          >
            Clear
          </button>
        </div>
      )}

      {/* Profile list */}
      <div className="flex-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <div className="text-center text-gray-500 text-xs py-8">
            {profiles.length === 0 ? "No profiles yet" : "No matches"}
          </div>
        )}
        {filtered.map((profile) => (
          <div
            key={profile.id}
            className={`flex items-start gap-2 w-full px-3 py-2.5 rounded-md mb-1 transition-colors ${
              selectedId === profile.id
                ? "bg-surface-3 border border-border-hover"
                : selected.has(profile.id)
                  ? "bg-surface-2 border border-accent/40"
                  : "hover:bg-surface-2 border border-transparent"
            }`}
          >
            {bulkEnabled && (
              <input
                type="checkbox"
                checked={selected.has(profile.id)}
                onChange={() => toggleSelect(profile.id)}
                onClick={(e) => e.stopPropagation()}
                aria-label={`Select ${profile.name}`}
                className="mt-1 cursor-pointer accent-emerald-500"
              />
            )}
            <button
              onClick={() => onSelect(profile.id)}
              className="flex-1 text-left"
            >
            <div className="flex items-center gap-2">
              <StatusIndicator status={profile.status} />
              <span className="text-sm font-medium truncate">{profile.name}</span>
            </div>
            <div className="flex items-center gap-2 mt-1 ml-4">
              <span className="text-xs text-gray-500 capitalize">{profile.platform}</span>
              {profile.proxy && (
                <>
                  <span className="text-xs text-gray-600">·</span>
                  <span className="text-xs text-gray-500">Proxy</span>
                </>
              )}
              {profile.region && (
                <>
                  <span className="text-xs text-gray-600">·</span>
                  <span className="text-xs text-gray-500">{profile.region}</span>
                </>
              )}
            </div>
            {profile.tags.length > 0 && (
              <div className="flex gap-1 mt-1.5 ml-4 flex-wrap">
                {profile.tags.map((t) => (
                  <span
                    key={t.tag}
                    className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-4 text-gray-400"
                    style={t.color ? { backgroundColor: `${t.color}20`, color: t.color } : undefined}
                  >
                    {t.tag}
                  </span>
                ))}
              </div>
            )}
            </button>
          </div>
        ))}
      </div>

      {/* New profile button */}
      <div className="p-3 border-t border-border">
        <button onClick={onNew} className="btn-secondary w-full flex items-center justify-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          <span>New Profile</span>
        </button>
      </div>
    </div>
  );
}
