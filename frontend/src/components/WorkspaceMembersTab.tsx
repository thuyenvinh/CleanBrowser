import { useState } from "react";
import { Trash2, UserPlus } from "lucide-react";
import { useWorkspaceMembers } from "../hooks/useWorkspaceMembers";
import type { WorkspaceRole } from "../lib/workspaces";

const ROLES: WorkspaceRole[] = [
  "owner",
  "admin",
  "editor",
  "launcher",
  "viewer",
];

interface WorkspaceMembersTabProps {
  workspaceId: string;
  currentUserId: string;
}

export function WorkspaceMembersTab({
  workspaceId,
  currentUserId,
}: WorkspaceMembersTabProps) {
  const { members, loading, error, invite, updateRole, remove } =
    useWorkspaceMembers(workspaceId);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>("editor");
  const [inviting, setInviting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const ownerCount = members.filter((m) => m.role === "owner").length;

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setInviting(true);
    setNotice(null);
    const result = await invite(inviteEmail.trim(), inviteRole);
    setInviting(false);
    if (result) {
      setInviteEmail("");
      setNotice(`Invited ${result.email} as ${result.role}.`);
    }
  };

  const handleRoleChange = async (userId: string, role: WorkspaceRole) => {
    setNotice(null);
    await updateRole(userId, role);
  };

  const handleRemove = async (userId: string, email: string) => {
    if (!window.confirm(`Remove ${email} from this workspace?`)) return;
    setNotice(null);
    const ok = await remove(userId);
    if (ok) setNotice(`Removed ${email}.`);
  };

  return (
    <div className="space-y-4">
      <form
        onSubmit={handleInvite}
        className="flex flex-wrap items-end gap-2 bg-surface-2 border border-border rounded-md p-3"
      >
        <div className="flex-1 min-w-[180px]">
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Invite by email
          </label>
          <input
            type="email"
            required
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            placeholder="user@example.com"
            className="w-full h-8 px-2 rounded bg-surface-1 border border-border text-xs text-gray-100"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Role
          </label>
          <select
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value as WorkspaceRole)}
            className="h-8 px-2 rounded bg-surface-1 border border-border text-xs text-gray-100"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={inviting}
          className="h-8 px-3 rounded bg-accent hover:bg-accent/80 disabled:opacity-50 text-xs text-white flex items-center gap-1"
        >
          <UserPlus className="h-3.5 w-3.5" />
          {inviting ? "Inviting…" : "Invite"}
        </button>
      </form>

      {error && (
        <div className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded px-3 py-2">
          {error}
        </div>
      )}
      {notice && (
        <div className="text-xs text-green-400 bg-green-950/30 border border-green-900 rounded px-3 py-2">
          {notice}
        </div>
      )}

      <div className="border border-border rounded-md overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-surface-2 text-gray-400">
            <tr>
              <th className="text-left px-3 py-2 font-medium">Email</th>
              <th className="text-left px-3 py-2 font-medium">Role</th>
              <th className="text-left px-3 py-2 font-medium">Joined</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td
                  colSpan={4}
                  className="px-3 py-4 text-center text-gray-500"
                >
                  Loading…
                </td>
              </tr>
            )}
            {!loading && members.length === 0 && (
              <tr>
                <td
                  colSpan={4}
                  className="px-3 py-4 text-center text-gray-500"
                >
                  No members yet.
                </td>
              </tr>
            )}
            {members.map((m) => {
              const isSelf = m.user_id === currentUserId;
              const lastOwner = m.role === "owner" && ownerCount <= 1;
              return (
                <tr
                  key={m.user_id}
                  className="border-t border-border text-gray-200"
                >
                  <td className="px-3 py-2 truncate">{m.email}</td>
                  <td className="px-3 py-2">
                    <select
                      value={m.role}
                      disabled={lastOwner}
                      onChange={(e) =>
                        handleRoleChange(
                          m.user_id,
                          e.target.value as WorkspaceRole,
                        )
                      }
                      className="h-7 px-2 rounded bg-surface-1 border border-border text-xs text-gray-100 disabled:opacity-50"
                      title={
                        lastOwner
                          ? "Can't demote the last owner"
                          : undefined
                      }
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2 text-gray-400">
                    {m.created_at ? m.created_at.slice(0, 10) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => handleRemove(m.user_id, m.email)}
                      disabled={lastOwner}
                      title={
                        lastOwner
                          ? "Can't remove the last owner"
                          : isSelf
                            ? "Leave workspace"
                            : "Remove member"
                      }
                      className="h-7 w-7 inline-flex items-center justify-center rounded text-gray-400 hover:text-red-400 hover:bg-surface-2 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
