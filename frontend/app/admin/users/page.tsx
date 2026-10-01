"use client";

import { useEffect, useState } from "react";
import { adminApi } from "@/lib/api";
import type { AdminUser } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Field, Input, Spinner } from "@/components/ui";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // inline credit-adjust form state
  const [adjustId, setAdjustId] = useState<string | null>(null);
  const [delta, setDelta] = useState("");
  const [note, setNote] = useState("");
  // manual user creation form state
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState<"user" | "admin">("user");
  const [newGrant, setNewGrant] = useState("");

  async function load(query = q) {
    try {
      setUsers(await adminApi.users(query));
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load users");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run(id: string, fn: () => Promise<unknown>) {
    setBusyId(id);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "action failed");
    } finally {
      setBusyId(null);
    }
  }

  async function submitAdjust(id: string) {
    const d = parseInt(delta, 10);
    if (!d || Number.isNaN(d)) {
      setError("enter a non-zero delta, e.g. 25 or -10");
      return;
    }
    await run(id, () => adminApi.adjustCredits(id, d, note));
    setAdjustId(null);
    setDelta("");
    setNote("");
  }

  async function submitCreate() {
    if (!newEmail.trim() || newPassword.length < 6) {
      setError("email is required and password must be at least 6 characters");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      await adminApi.createUser({
        email: newEmail.trim(),
        password: newPassword,
        display_name: newName.trim() || undefined,
        role: newRole,
        grant_credits: parseInt(newGrant, 10) || 0,
      });
      setShowCreate(false);
      setNewEmail(""); setNewPassword(""); setNewName(""); setNewRole("user"); setNewGrant("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to create user");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Input
          placeholder="Search by email or name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          className="max-w-sm"
        />
        <Button variant="outline" onClick={() => load()}>Search</Button>
        <Button className="ml-auto" onClick={() => { setShowCreate(!showCreate); setError(null); }}>
          {showCreate ? "Cancel" : "+ New user"}
        </Button>
      </div>

      {showCreate && (
        <Card className="p-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Email">
              <Input
                type="email" placeholder="user@example.com" value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
              />
            </Field>
            <Field label="Password" hint="At least 6 characters">
              <Input
                type="password" placeholder="initial password" value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </Field>
            <Field label="Display name" hint="Optional">
              <Input
                placeholder="Jane Doe" value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </Field>
            <Field label="Role" hint="Admins get panel access">
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as "user" | "admin")}
                className="gs-focus h-10 rounded-lg bg-surface-2 border border-line px-3 text-sm text-fg focus:border-accent-line"
              >
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </Field>
            <Field label="Extra credits" hint="On top of the signup grant; optional">
              <Input
                type="number" min={0} placeholder="0" value={newGrant}
                onChange={(e) => setNewGrant(e.target.value)}
              />
            </Field>
            <div className="flex items-end">
              <Button
                variant="primary" disabled={creating} onClick={submitCreate}
                className="w-full sm:w-auto"
              >
                {creating ? <Spinner className="text-white" /> : "Create user"}
              </Button>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-faint">
            The account is created with the email already confirmed — share the
            password with the user so they can log in.
          </p>
        </Card>
      )}

      <ErrorText>{error}</ErrorText>

      <Card className="overflow-x-auto">
        {users === null ? (
          <div className="grid place-items-center py-12"><Spinner className="text-accent" /></div>
        ) : users.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted">No users match.</p>
        ) : (
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 text-right font-medium">Balance</th>
                <th className="px-4 py-3 text-right font-medium">Gens</th>
                <th className="px-4 py-3 text-right font-medium">Spent</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--line)]">
              {users.map((u) => (
                <tr key={u.id} className="align-middle">
                  <td className="px-4 py-3">
                    <div className="font-medium">{u.display_name || u.email.split("@")[0]}</div>
                    <div className="text-xs text-faint">{u.email}</div>
                  </td>
                  <td className="px-4 py-3">
                    {u.role === "admin" ? <Badge tone="accent">admin</Badge> : <span className="text-muted">user</span>}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={u.status === "active" ? "success" : "danger"}>{u.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">{u.balance}</td>
                  <td className="px-4 py-3 text-right font-mono text-muted">{u.generations}</td>
                  <td className="px-4 py-3 text-right font-mono text-muted">{u.credits_spent}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1.5">
                      <Button
                        variant="ghost"
                        className="h-8 px-2 text-xs"
                        disabled={busyId === u.id}
                        onClick={() => { setAdjustId(adjustId === u.id ? null : u.id); setError(null); }}
                      >
                        Credits
                      </Button>
                      <Button
                        variant={u.status === "active" ? "danger" : "outline"}
                        className="h-8 px-2 text-xs"
                        disabled={busyId === u.id}
                        onClick={() =>
                          run(u.id, () =>
                            adminApi.setUserStatus(u.id, u.status === "active" ? "suspended" : "active"),
                          )
                        }
                      >
                        {u.status === "active" ? "Suspend" : "Activate"}
                      </Button>
                    </div>
                    {adjustId === u.id && (
                      <div className="mt-2 flex items-center justify-end gap-1.5">
                        <Input
                          placeholder="+25 / -10"
                          value={delta}
                          onChange={(e) => setDelta(e.target.value)}
                          className="h-8 w-24 text-xs"
                        />
                        <Input
                          placeholder="note (optional)"
                          value={note}
                          onChange={(e) => setNote(e.target.value)}
                          className="h-8 w-40 text-xs"
                        />
                        <Button
                          variant="primary"
                          className="h-8 px-2 text-xs"
                          disabled={busyId === u.id}
                          onClick={() => submitAdjust(u.id)}
                        >
                          Apply
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}