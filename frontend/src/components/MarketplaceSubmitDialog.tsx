import { useState } from "react";
import { Loader2, Send, X } from "lucide-react";
import type {
  MarketplaceApp,
  MarketplaceAppSubmit,
} from "../lib/marketplace";

interface MarketplaceSubmitDialogProps {
  onClose: () => void;
  onSubmit: (
    input: MarketplaceAppSubmit,
  ) => Promise<MarketplaceApp | undefined>;
}

// Mirror the category set seeded by backend migration 0018 so the dropdown
// stays in sync with what the public listing actually filters on. Free-form
// "other" is allowed for forward-compat with future category expansion.
const CATEGORIES = ["social", "ecommerce", "data", "misc"] as const;

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function MarketplaceSubmitDialog({
  onClose,
  onSubmit,
}: MarketplaceSubmitDialogProps) {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<string>("misc");
  // Phase 6 phase 2 ships flow submissions only — script bundle uploads
  // require a separate sandboxing review and land in a later wave.
  const kind: "flow" = "flow";
  const [dslText, setDslText] = useState(
    '{\n  "version": 1,\n  "start": "n1",\n  "nodes": [\n    {"id": "n1", "type": "log", "params": {"message": "hello"}}\n  ]\n}',
  );
  const [creatorName, setCreatorName] = useState("");
  const [creatorUrl, setCreatorUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function validate(): MarketplaceAppSubmit | null {
    const s = slug.trim();
    if (!SLUG_PATTERN.test(s) || s.length < 3 || s.length > 80) {
      setError(
        "slug must be 3-80 chars, lowercase alphanumeric with dashes (no leading/trailing dash)",
      );
      return null;
    }
    const n = name.trim();
    if (!n) {
      setError("name is required");
      return null;
    }
    let dsl: object;
    try {
      dsl = JSON.parse(dslText);
    } catch {
      setError("DSL JSON is not valid JSON");
      return null;
    }
    if (
      typeof dsl !== "object" ||
      dsl === null ||
      !Array.isArray((dsl as { nodes?: unknown }).nodes)
    ) {
      setError("DSL JSON must contain a 'nodes' array");
      return null;
    }
    return {
      slug: s,
      name: n,
      kind,
      description: description.trim() || undefined,
      category: category || undefined,
      dsl_json: dsl,
      creator_name: creatorName.trim() || undefined,
      creator_url: creatorUrl.trim() || undefined,
    };
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const payload = validate();
    if (!payload) return;
    setSubmitting(true);
    try {
      const created = await onSubmit(payload);
      if (created) onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface-1 border border-border rounded-lg w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <h3 className="text-sm font-medium text-gray-100">Submit your app</h3>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-200"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          onSubmit={handleSubmit}
          className="flex-1 overflow-y-auto p-5 space-y-4"
        >
          {error && (
            <div className="px-3 py-2 bg-red-600/15 border border-red-600/30 text-red-400 text-xs rounded">
              {error}
            </div>
          )}

          <p className="text-xs text-gray-500">
            Submissions are reviewed by moderators before appearing in the
            public catalog.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Slug <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="my-cool-flow"
                className="w-full px-2 py-1.5 text-sm bg-surface-2 border border-border rounded text-gray-100"
                required
              />
              <p className="text-[10px] text-gray-600 mt-1">
                URL-safe id. Lowercase letters, digits, dashes.
              </p>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Name <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My Cool Flow"
                maxLength={200}
                className="w-full px-2 py-1.5 text-sm bg-surface-2 border border-border rounded text-gray-100"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Short description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One-line summary shown on the catalog card."
              className="w-full px-2 py-1.5 text-sm bg-surface-2 border border-border rounded text-gray-100"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Category</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full px-2 py-1.5 text-sm bg-surface-2 border border-border rounded text-gray-100"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Kind</label>
              <input
                type="text"
                value="flow"
                disabled
                className="w-full px-2 py-1.5 text-sm bg-surface-2 border border-border rounded text-gray-500"
              />
              <p className="text-[10px] text-gray-600 mt-1">
                Script submissions ship in a later phase.
              </p>
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Flow DSL JSON <span className="text-red-400">*</span>
            </label>
            <textarea
              value={dslText}
              onChange={(e) => setDslText(e.target.value)}
              spellCheck={false}
              rows={10}
              className="w-full px-2 py-1.5 text-xs font-mono bg-surface-2 border border-border rounded text-gray-100"
              required
            />
            <p className="text-[10px] text-gray-600 mt-1">
              Must be valid JSON with a top-level <code>nodes</code> array.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Creator name
              </label>
              <input
                type="text"
                value={creatorName}
                onChange={(e) => setCreatorName(e.target.value)}
                placeholder="Defaults to your email"
                className="w-full px-2 py-1.5 text-sm bg-surface-2 border border-border rounded text-gray-100"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Creator URL
              </label>
              <input
                type="url"
                value={creatorUrl}
                onChange={(e) => setCreatorUrl(e.target.value)}
                placeholder="https://..."
                className="w-full px-2 py-1.5 text-sm bg-surface-2 border border-border rounded text-gray-100"
              />
            </div>
          </div>
        </form>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 text-xs rounded border border-border text-gray-300 hover:bg-surface-2"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-60"
          >
            {submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            Submit for review
          </button>
        </div>
      </div>
    </div>
  );
}
