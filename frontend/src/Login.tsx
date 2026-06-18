import { useState } from 'react';
import { setToken } from './auth';

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || 'Falha no login');
      }
      const data = await res.json();
      if (data.access_token) setToken(data.access_token);
      onSuccess();
    } catch (err: any) {
      setError(err.message || 'Erro');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 text-zinc-100 p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 p-8 rounded-2xl border border-white/10 bg-white/5">
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-bold">Cristopher</h1>
          <p className="text-sm text-zinc-400">Introduz a password para entrar</p>
        </div>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          className="w-full px-4 py-3 rounded-xl bg-zinc-900 border border-white/10 outline-none focus:border-white/30"
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={loading || !password}
          className="w-full py-3 rounded-xl bg-white text-zinc-900 font-semibold disabled:opacity-40"
        >
          {loading ? 'A entrar…' : 'Entrar'}
        </button>
      </form>
    </div>
  );
}
