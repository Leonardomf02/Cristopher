import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { format, startOfWeek, startOfMonth, endOfMonth, subDays } from 'date-fns';
import { pt } from 'date-fns/locale';
import { X, Trophy, Skull, TrendingUp, RefreshCw, Settings, Search, ChevronLeft, ChevronRight, Star } from 'lucide-react';
import { lolApi } from '../api';
import {
  LolGame, LolStats, RankInfo, LiveGame, LiveGameDetailed, LivePlayer,
  LiveTeamStats, LivePlayerTag, MatchupEntry, MatchupAnalysis,
  DuoDetection, ChampionPoolDepth, MentalState, RankTrajectory,
  HeadToHead, TeamCompAnalysis, WinProbability, StrategicTip,
  ChampionMastery, MatchTimeline, SummonerInfo, RankPosition,
  ChampSelectStatus, ChampSelectSession, ChampSuggestion, TeamComp,
} from '../types';

type DateFilter = 'today' | 'week' | 'month' | 'all';

export default function LolPage() {
  const [games, setGames] = useState<LolGame[]>([]);
  const [stats, setStats] = useState<LolStats | null>(null);
  // Riot API sync state
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [riotGameName, setRiotGameName] = useState('Cristóvão');
  const [riotTagLine, setRiotTagLine] = useState('2002');
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<{ imported: number } | null>(null);

  // New Riot API data
  const [rankInfo, setRankInfo] = useState<RankInfo | null>(null);
  const [liveGame, setLiveGame] = useState<LiveGame | null>(null);
  const [liveDetailed, setLiveDetailed] = useState<LiveGameDetailed | null>(null);
  const [mastery, setMastery] = useState<ChampionMastery[]>([]);
  const [selectedTimeline, setSelectedTimeline] = useState<MatchTimeline | null>(null);
  const [summoner, setSummoner] = useState<SummonerInfo | null>(null);
  const [ddVersion, setDdVersion] = useState('16.7.1');

  // Champ Select state
  const [csStatus, setCsStatus] = useState<ChampSelectStatus | null>(null);
  const [csSession, setCsSession] = useState<ChampSelectSession | null>(null);
  const csPolling = useRef<ReturnType<typeof setInterval> | null>(null);
  const livePolling = useRef<ReturnType<typeof setInterval> | null>(null);
  const wasInGame = useRef(false);

  // Date filter & ranking
  const [dateFilter, setDateFilter] = useState<DateFilter>('today');
  const [rankPosition, setRankPosition] = useState<any>(null);
  const [peakStats, setPeakStats] = useState<any>(null);

  // Season stats + seasons list
  // selectedSeasonId: null = "Season atual" (resolves to active), 'all' = sem filtro, number = season específica
  const [seasonStats, setSeasonStats] = useState<any>(null);
  const [seasons, setSeasons] = useState<any[]>([]);
  const [selectedSeasonId, setSelectedSeasonId] = useState<number | 'all' | null>(null);

  // Effective season_id sent to backend: undefined when 'all', else explicit id (active when null)
  const effectiveSeasonId = useMemo<number | undefined>(() => {
    if (selectedSeasonId === 'all') return undefined;
    if (typeof selectedSeasonId === 'number') return selectedSeasonId;
    const active = seasons.find(s => s.active);
    return active?.id;
  }, [selectedSeasonId, seasons]);

  // Meta tier list
  const [metaChampions, setMetaChampions] = useState<any[]>([]);
  const [showMetaTierList, setShowMetaTierList] = useState(false);
  const [metaSource, setMetaSource] = useState<string>('all');
  const [metaAvailableSources, setMetaAvailableSources] = useState<string[]>([]);
  const [metaTierFilter, setMetaTierFilter] = useState<string>('all');
  const [metaSort, setMetaSort] = useState<string>('tier');
  const [metaSortDir, setMetaSortDir] = useState<'asc' | 'desc'>('asc');
  const [metaSearch, setMetaSearch] = useState<string>('');
  const [metaLoading, setMetaLoading] = useState(false);
  const [metaError, setMetaError] = useState(false);

  // Tab state: 'main' or 'stats'
  const [activeTab, setActiveTab] = useState<'main' | 'stats'>('main');
  const [detailedStats, setDetailedStats] = useState<any>(null);

  // Stats tab: champion search filter
  const [statsChampFilter, setStatsChampFilter] = useState('');
  const [statsChampMode, setStatsChampMode] = useState<'all' | 'played' | 'against'>('all');

  // Stats tab: month navigation for daily performance
  const [perfMonth, setPerfMonth] = useState(() => format(new Date(), 'yyyy-MM'));

  // AI Prediction stats
  const [predStats, setPredStats] = useState<any>(null);
  const [predHistory, setPredHistory] = useState<any[]>([]);
  const [predCalibration, setPredCalibration] = useState<any>(null);



  // Filtered stats based on champion search
  const filteredDetailedStats = useMemo(() => {
    if (!detailedStats || !statsChampFilter.trim()) return detailedStats;
    const q = statsChampFilter.toLowerCase();
    const filtered = { ...detailedStats };
    // Filter champion stats
    if (filtered.champion_stats) {
      filtered.champion_stats = filtered.champion_stats.filter((c: any) =>
        c.champion?.toLowerCase().includes(q)
      );
    }
    // Filter most faced
    if (filtered.most_faced) {
      filtered.most_faced = filtered.most_faced.filter((c: any) =>
        c.champion?.toLowerCase().includes(q)
      );
    }
    // Filter winrate history — show only games with matching champion
    // (we don't have per-game champion in winrate_history, so skip filtering)
    return filtered;
  }, [detailedStats, statsChampFilter]);

  // Filtered games based on champion search (played with OR against)
  const filteredStatGames = useMemo(() => {
    if (!statsChampFilter.trim()) return [];
    const q = statsChampFilter.toLowerCase();
    return games.filter(g => {
      const matchPlayed = g.champion_played?.toLowerCase().includes(q);
      const matchAgainst = g.champion_against?.toLowerCase().includes(q);
      if (statsChampMode === 'played') return matchPlayed;
      if (statsChampMode === 'against') return matchAgainst;
      return matchPlayed || matchAgainst;
    });
  }, [games, statsChampFilter, statsChampMode]);

  // Daily performance filtered by month
  const filteredDailyPerf = useMemo(() => {
    if (!detailedStats?.daily_performance) return [];
    return detailedStats.daily_performance.filter((d: any) => d.date.startsWith(perfMonth));
  }, [detailedStats, perfMonth]);

  // Available months from daily data
  const availableMonths = useMemo((): string[] => {
    if (!detailedStats?.daily_performance) return [];
    const months = new Set(detailedStats.daily_performance.map((d: any) => d.date.substring(0, 7)));
    return Array.from(months).sort().reverse() as string[];
  }, [detailedStats]);

  useEffect(() => {
    loadData(); loadRiotConfig(); loadRiotData(); loadSeasonStats(); loadSeasons(); loadMetaTierList();

  }, []);

  useEffect(() => {
    fetch('https://ddragon.leagueoflegends.com/api/versions.json')
      .then(r => r.json())
      .then(v => { if (v?.[0]) setDdVersion(v[0]); })
      .catch(() => {});
  }, []);

  // Poll champ select: status every 5s, session every 2s when active
  const pollChampSelect = useCallback(async () => {
    try {
      const status = await lolApi.getChampSelectStatus();
      setCsStatus(status);
      if (status.in_champ_select) {
        const session = await lolApi.getChampSelectSession();
        setCsSession(session);
      } else {
        setCsSession(null);
      }
    } catch { /* Client not reachable */ }
  }, []);

  useEffect(() => {
    pollChampSelect();
    csPolling.current = setInterval(pollChampSelect, 3000);
    return () => { if (csPolling.current) clearInterval(csPolling.current); };
  }, [pollChampSelect]);

  // Poll live game status every 30s, detailed data every 60s when in game
  useEffect(() => {
    const pollLive = async () => {
      try {
        const live = await lolApi.getLive();
        setLiveGame(live);
        if (live?.in_game) {
          wasInGame.current = true;
          const detailed = await lolApi.getLiveDetailed();
          if (detailed) setLiveDetailed(detailed);
        } else {
          setLiveDetailed(null);
          // Game just ended — auto-sync games and resolve predictions
          if (wasInGame.current) {
            wasInGame.current = false;
            try {
              await lolApi.syncRiot();
              await loadData();
              if (activeTab === 'stats') loadPredictionStats();
            } catch { /* ignore */ }
          }
        }
      } catch { /* ignore */ }
    };
    livePolling.current = setInterval(pollLive, 30000);
    return () => { if (livePolling.current) clearInterval(livePolling.current); };
  }, [activeTab, dateFilter]);

  async function loadData(filter?: DateFilter, seasonOverride?: number | undefined | 'unset') {
    const f = filter ?? dateFilter;
    const sid = seasonOverride === 'unset' ? undefined : (seasonOverride !== undefined ? seasonOverride : effectiveSeasonId);
    const params: { start_date?: string; end_date?: string; season_id?: number } = {};
    const today = format(new Date(), 'yyyy-MM-dd');
    if (f === 'today') {
      params.start_date = today;
      params.end_date = today;
    } else if (f === 'week') {
      params.start_date = format(startOfWeek(new Date(), { weekStartsOn: 1 }), 'yyyy-MM-dd');
      params.end_date = today;
    } else if (f === 'month') {
      params.start_date = format(startOfMonth(new Date()), 'yyyy-MM-dd');
      params.end_date = format(endOfMonth(new Date()), 'yyyy-MM-dd');
    }
    // 'all' → no date params
    if (sid !== undefined) params.season_id = sid;
    const [gamesData, statsData] = await Promise.all([
      lolApi.list(Object.keys(params).length > 0 ? params : undefined),
      lolApi.stats(Object.keys(params).length > 0 ? params : undefined),
    ]);
    setGames(gamesData);
    setStats(statsData);
  }

  async function loadRiotData() {
    try {
      // Batch 1: lightweight calls (1-2 API requests each)
      const [rank, live, summ, pos] = await Promise.all([
        lolApi.getRank().catch(() => null),
        lolApi.getLive().catch(() => null),
        lolApi.getSummoner().catch(() => null),
        lolApi.getPosition().catch(() => null),
      ]);
      if (rank) setRankInfo(rank);
      if (live) {
        setLiveGame(live);
        // If in game, fetch detailed stats for all players
        if (live.in_game) {
          lolApi.getLiveDetailed().then(d => { if (d) setLiveDetailed(d); }).catch(() => {});
        } else {
          setLiveDetailed(null);
        }
      }
      if (summ) setSummoner(summ);
      if (pos && (pos.euw_rank || pos.global_rank)) setRankPosition(pos);

      // Fetch peak stats (after rank+position have been fetched and snapshotted)
      lolApi.getPeak().then(p => { if (p?.has_data) setPeakStats(p); }).catch(() => {});

      // Batch 2: mastery needs champion map loading
      const mast = await lolApi.getMastery(10).catch(() => []);
      if (mast) setMastery(mast);
    } catch { /* ignore */ }
  }

  async function loadSeasonStats() {
    try {
      // 'all' não tem endpoint dedicado — esconde o painel de season nesse modo
      if (selectedSeasonId === 'all') { setSeasonStats(null); return; }
      const sid = typeof selectedSeasonId === 'number' ? selectedSeasonId : undefined;
      const data = sid ? await lolApi.seasonStatsById(sid) : await lolApi.seasonStats();
      setSeasonStats(data);
    } catch { /* ignore */ }
  }

  async function loadSeasons() {
    try {
      const data = await lolApi.listSeasons();
      setSeasons(data || []);
    } catch { /* ignore */ }
  }

  async function handleManualReset() {
    if (!confirm('Fechar a season atual e abrir uma nova? Os dados ficam guardados.')) return;
    await lolApi.resetSeason();
    await loadSeasons();
    setSelectedSeasonId(null);
    loadSeasonStats();
  }

  // Reload everything (season-scoped) whenever the user picks a different season
  useEffect(() => {
    if (seasons.length === 0) return;
    loadSeasonStats();
    loadData();
    if (activeTab === 'stats' || detailedStats) loadDetailedStats();
  }, [selectedSeasonId, seasons]);

  async function loadMetaTierList(source?: string, retries = 2) {
    setMetaLoading(true);
    setMetaError(false);
    try {
      const data = await lolApi.getMetaStats(source ?? metaSource);
      if (data?.loaded && data.champions && data.champions.length > 0) {
        setMetaChampions(data.champions);
        if (data.available_sources) setMetaAvailableSources(data.available_sources);
        setMetaLoading(false);
        return;
      }
      // Data wasn't ready yet — retry after a delay
      if (retries > 0) {
        await new Promise(r => setTimeout(r, 3000));
        setMetaLoading(false);
        return loadMetaTierList(source, retries - 1);
      }
      setMetaError(true);
    } catch {
      if (retries > 0) {
        await new Promise(r => setTimeout(r, 3000));
        setMetaLoading(false);
        return loadMetaTierList(source, retries - 1);
      }
      setMetaError(true);
    } finally {
      setMetaLoading(false);
    }
  }

  async function loadDetailedStats(filter?: DateFilter, seasonOverride?: number | undefined | 'unset') {
    try {
      const f = filter ?? dateFilter;
      const sid = seasonOverride === 'unset' ? undefined : (seasonOverride !== undefined ? seasonOverride : effectiveSeasonId);
      const params: { start_date?: string; end_date?: string; season_id?: number } = {};
      const today = format(new Date(), 'yyyy-MM-dd');
      if (f === 'today') {
        params.start_date = today;
        params.end_date = today;
      } else if (f === 'week') {
        params.start_date = format(startOfWeek(new Date(), { weekStartsOn: 1 }), 'yyyy-MM-dd');
        params.end_date = today;
      } else if (f === 'month') {
        params.start_date = format(startOfMonth(new Date()), 'yyyy-MM-dd');
        params.end_date = format(endOfMonth(new Date()), 'yyyy-MM-dd');
      }
      // 'all' → no date params
      if (sid !== undefined) params.season_id = sid;
      const data = await lolApi.detailedStats(Object.keys(params).length > 0 ? params : undefined);
      setDetailedStats(data);
    } catch { /* ignore */ }
  }

  async function loadPredictionStats() {
    try {
      const [stats, history, calibration] = await Promise.all([
        lolApi.getPredictionStats(),
        lolApi.getPredictions(20),
        lolApi.getPredictionCalibration(),
      ]);
      setPredStats(stats);
      setPredHistory(history);
      setPredCalibration(calibration);
    } catch { /* ignore */ }
  }

  async function loadTimeline(matchId: string) {
    try {
      const tl = await lolApi.getTimeline(matchId);
      setSelectedTimeline(tl);
    } catch { setSelectedTimeline(null); }
  }

  async function loadRiotConfig() {
    try {
      const config = await lolApi.getRiotConfig();
      if (config.game_name) setRiotGameName(config.game_name);
      if (config.tag_line) setRiotTagLine(config.tag_line);
    } catch { /* no config yet */ }
  }

  async function handleSaveConfig() {
    await lolApi.setRiotConfig({ game_name: riotGameName, tag_line: riotTagLine });
    await loadRiotConfig();
    setShowConfigModal(false);
  }

  async function handleSync(days?: number, season?: boolean) {
    setSyncing(true);
    setSyncResult(null);
    try {
      const result = await lolApi.syncRiot(days, season);
      setSyncResult({ imported: result.imported });
      loadData();
      if (season || (days && days > 7)) {
        loadSeasonStats();
        loadDetailedStats();
      }
    } catch (err: any) {
      alert(err.message || 'Erro ao sincronizar');
    } finally {
      setSyncing(false);
    }
  }

  async function handleDelete(id: number) {
    await lolApi.delete(id);
    loadData();
  }

  // Group games by date
  const gamesByDate: Record<string, LolGame[]> = {};
  games.forEach(g => {
    if (!gamesByDate[g.date]) gamesByDate[g.date] = [];
    gamesByDate[g.date].push(g);
  });

  const champStatsArr = stats ? Object.entries(stats.champion_stats)
    .map(([name, s]) => ({ name, ...s, winrate: s.games > 0 ? Math.round(s.wins / s.games * 100) : 0 }))
    .sort((a, b) => b.games - a.games) : [];

  return (
    <div>
      {/* ── Champ Select Helper ──────────────────────────────────── */}
      {csStatus?.client_running && (
        <div className={`mb-6 rounded-2xl border overflow-hidden transition-all ${
          csSession?.active
            ? 'bg-gradient-to-r from-[#1a1020] to-[#161616] border-purple-500/40'
            : 'bg-[#161616] border-[#222]'
        }`}>
          <div className="flex items-center gap-3 px-4 py-3">
            <div className={`w-2.5 h-2.5 rounded-full ${
              csSession?.active ? 'bg-purple-500 animate-pulse' : 'bg-gray-600'
            }`} />
            <span className="text-sm font-medium">
              {csSession?.active ? 'Champ Select Ativo' : 'League Client conectado'}
            </span>
            {csStatus.phase && csStatus.phase !== 'None' && !csSession?.active && (
              <span className="text-xs text-gray-500">{csStatus.phase}</span>
            )}
          </div>

          {csSession?.active && (
            <div className="px-4 pb-4 space-y-4">
              {/* Teams */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* My Team */}
                <div>
                  <p className="text-[10px] text-blue-400 font-medium mb-2 uppercase tracking-wider">Tua Equipa</p>
                  <div className="space-y-1.5">
                    {csSession.my_team?.map((p, i) => (
                      <div key={i} className={`flex items-center gap-2 px-2 py-1.5 rounded-lg ${
                        p.is_local_player ? 'bg-blue-500/15 border border-blue-500/30' : 'bg-[#111]'
                      }`}>
                        <span className="text-[10px] text-gray-500 w-10 truncate">{p.position || '?'}</span>
                        <span className={`text-xs font-medium ${p.champion_name ? 'text-blue-300' : 'text-gray-600'}`}>
                          {p.champion_name || '—'}
                        </span>
                        {p.is_local_player && <span className="text-[9px] text-blue-400 ml-auto">TU</span>}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Enemy Team */}
                <div>
                  <p className="text-[10px] text-red-400 font-medium mb-2 uppercase tracking-wider">Equipa Inimiga</p>
                  <div className="space-y-1.5">
                    {csSession.their_team?.map((p, i) => (
                      <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-[#111]">
                        <span className="text-[10px] text-gray-500 w-10 truncate">{p.position || '?'}</span>
                        <span className={`text-xs font-medium ${p.champion_name ? 'text-red-300' : 'text-gray-600'}`}>
                          {p.champion_name || '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Bans */}
              {((csSession.my_bans?.length ?? 0) > 0 || (csSession.their_bans?.length ?? 0) > 0) && (
                <div className="flex items-center gap-4 text-[10px]">
                  <span className="text-gray-500">Bans:</span>
                  <div className="flex gap-1 flex-wrap">
                    {csSession.my_bans?.map((b, i) => (
                      <span key={`m${i}`} className="px-1.5 py-0.5 bg-blue-500/10 text-blue-400 rounded">{b}</span>
                    ))}
                    {csSession.their_bans?.map((b, i) => (
                      <span key={`t${i}`} className="px-1.5 py-0.5 bg-red-500/10 text-red-400 rounded">{b}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* Team Comp Analysis */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <CompAnalysis label="Tua Equipa" comp={csSession.my_comp} color="blue" />
                <CompAnalysis label="Inimigo" comp={csSession.their_comp} color="red" />
              </div>

              {/* Warnings */}
              {csSession.my_comp?.warnings && csSession.my_comp.warnings.length > 0 && (
                <div className="space-y-1">
                  {csSession.my_comp.warnings.map((w, i) => (
                    <p key={i} className="text-xs text-yellow-400 bg-yellow-500/10 rounded-lg px-3 py-1.5">{w}</p>
                  ))}
                </div>
              )}

              {/* Enemy Counters — shown BEFORE suggestions for prominence */}
              {csSession.enemy_counters && Object.keys(csSession.enemy_counters).length > 0 && (
                <div>
                  <p className="text-[10px] text-red-400 font-medium mb-2 uppercase tracking-wider">🎯 Os teus picks contra cada inimigo</p>
                  <div className="space-y-3">
                    {Object.entries(csSession.enemy_counters).map(([enemy, picks]) => (
                      picks.length > 0 && (
                        <div key={enemy} className="bg-[#0d0d0d] rounded-lg p-3 border border-red-500/20">
                          <p className="text-xs text-red-300 font-semibold mb-2">vs {enemy}</p>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                            {picks.slice(0, 6).map((p) => (
                              <div key={p.champion} className={`flex items-center justify-between px-2 py-1 rounded ${
                                p.winrate >= 60 ? 'bg-green-500/10 border border-green-500/20' :
                                p.winrate >= 50 ? 'bg-gray-500/10 border border-[#333]' :
                                'bg-red-500/10 border border-red-500/20'
                              }`}>
                                <span className="text-[11px] font-medium text-white">{p.champion}</span>
                                <span className={`text-[10px] font-semibold ${
                                  p.winrate >= 60 ? 'text-green-400' : p.winrate >= 50 ? 'text-gray-400' : 'text-red-400'
                                }`}>{p.winrate}% <span className="text-gray-500 font-normal">({p.wins}W {p.losses}L)</span></span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )
                    ))}
                  </div>
                </div>
              )}

              {/* Pick Suggestions */}
              {csSession.suggestions && csSession.suggestions.length > 0 && (
                <div>
                  <p className="text-[10px] text-purple-400 font-medium mb-2 uppercase tracking-wider">Sugestões de Pick</p>
                  <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                    {csSession.suggestions.slice(0, 8).map((s) => (
                      <div key={s.champion} className={`bg-[#111] rounded-lg p-2 border ${
                        s.score >= 70 ? 'border-green-500/30' : s.score >= 50 ? 'border-[#333]' : 'border-red-500/20'
                      }`}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium text-white truncate">{s.champion_name}</span>
                          <span className={`text-[10px] font-bold ${
                            s.score >= 70 ? 'text-green-400' : s.score >= 50 ? 'text-gray-400' : 'text-red-400'
                          }`}>{s.score}</span>
                        </div>
                        <div className="flex items-center gap-1 mb-1">
                          <span className={`text-[9px] px-1 py-0.5 rounded ${
                            s.damage === 'AP' ? 'bg-purple-500/20 text-purple-300' :
                            s.damage === 'AD' ? 'bg-orange-500/20 text-orange-300' :
                            'bg-gray-500/20 text-gray-400'
                          }`}>{s.damage}</span>
                          <span className={`text-[9px] font-medium ${
                            s.winrate >= 60 ? 'text-green-400' : s.winrate >= 50 ? 'text-gray-400' : 'text-red-400'
                          }`}>{s.winrate}% ({s.games}g)</span>
                          {s.meta_wr != null && (
                            <span className={`text-[9px] font-medium ${
                              s.meta_wr >= 52 ? 'text-cyan-400' : s.meta_wr >= 50 ? 'text-gray-500' : 'text-red-400/60'
                            }`}>🌍{s.meta_wr}%</span>
                          )}
                        </div>
                        {s.reasons.length > 1 && (
                          <div className="space-y-0.5">
                            {s.reasons.slice(1, 3).map((r, i) => (
                              <p key={i} className="text-[9px] text-gray-500 leading-tight">{r}</p>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Live Game Detailed Stats — Porofessor-style */}
      {liveDetailed?.in_game && liveDetailed.my_team && liveDetailed.enemy_team && (
        <div className="mb-6 rounded-2xl border border-green-500/30 bg-gradient-to-b from-[#0a1a0a] to-[#111] overflow-hidden shadow-xl shadow-green-900/10">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#1a1a1a] bg-[#0a0a0a]">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" />
              <span className="text-sm font-bold text-green-400">Em Jogo</span>
              <span className="text-xs text-gray-500 bg-[#1a1a1a] rounded px-2 py-0.5">{liveDetailed.game_mode}</span>
              <span className="text-xs text-gray-600">{Math.floor((liveDetailed.game_length_seconds || 0) / 60)}:{String((liveDetailed.game_length_seconds || 0) % 60).padStart(2, '0')}</span>
            </div>
            {/* Bans */}
            {((liveDetailed.bans_my_team?.length ?? 0) > 0 || (liveDetailed.bans_enemy_team?.length ?? 0) > 0) && (
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-gray-500 font-medium">BANS</span>
                <div className="flex items-center gap-1">
                  {liveDetailed.bans_my_team?.map((b, i) => (
                    <img
                      key={`mb${i}`}
                      src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${b}.png`}
                      className="w-5 h-5 rounded border border-blue-500/30"
                      alt={b}
                      title={b}
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                  ))}
                </div>
                <span className="text-gray-700">vs</span>
                <div className="flex items-center gap-1">
                  {liveDetailed.bans_enemy_team?.map((b, i) => (
                    <img
                      key={`eb${i}`}
                      src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${b}.png`}
                      className="w-5 h-5 rounded border border-red-500/30"
                      alt={b}
                      title={b}
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Teams grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-0">
            {/* My Team */}
            <div className="border-r border-[#1a1a1a]">
              <div className="flex items-center justify-between px-4 py-2 bg-blue-500/5 border-b border-[#1a1a1a]">
                <span className="text-[10px] text-blue-400 font-bold uppercase tracking-wider">Tua Equipa</span>
                {liveDetailed.my_team_stats?.avg_rank_str && (
                  <span className="text-[10px] text-gray-500">Avg: {liveDetailed.my_team_stats.avg_rank_str}</span>
                )}
              </div>
              <div className="divide-y divide-[#151515]">
                {liveDetailed.my_team.map((p) => (
                  <LivePlayerRow key={p.puuid} player={p} ddVersion={ddVersion} />
                ))}
              </div>
              <TeamStatsBar stats={liveDetailed.my_team_stats} label="Stats" color="blue" />
            </div>
            {/* Enemy Team */}
            <div>
              <div className="flex items-center justify-between px-4 py-2 bg-red-500/5 border-b border-[#1a1a1a]">
                <span className="text-[10px] text-red-400 font-bold uppercase tracking-wider">Equipa Inimiga</span>
                {liveDetailed.enemy_team_stats?.avg_rank_str && (
                  <span className="text-[10px] text-gray-500">Avg: {liveDetailed.enemy_team_stats.avg_rank_str}</span>
                )}
              </div>
              <div className="divide-y divide-[#151515]">
                {liveDetailed.enemy_team.map((p) => (
                  <LivePlayerRow key={p.puuid} player={p} ddVersion={ddVersion} />
                ))}
              </div>
              <TeamStatsBar stats={liveDetailed.enemy_team_stats} label="Stats" color="red" />
            </div>
          </div>

          {/* Matchup Analysis */}
          <MatchupPanel analysis={liveDetailed.matchup_analysis} ddVersion={ddVersion} />

          {/* Personal Matchup WR */}
          <PersonalMatchupPanel
            personalMatchups={liveDetailed.personal_matchups}
            enemyTeam={liveDetailed.enemy_team}
            myTeam={liveDetailed.my_team}
            ddVersion={ddVersion}
          />

          {/* Win Probability */}
          <WinProbabilityBar wp={liveDetailed.win_probability} />

          {/* Team Comp Analysis */}
          <TeamCompDetailedPanel myComp={liveDetailed.my_comp_analysis} enemyComp={liveDetailed.enemy_comp_analysis} />

          {/* Duo Detection */}
          <DuoSection myDuos={liveDetailed.duos_my_team} enemyDuos={liveDetailed.duos_enemy_team} />

          {/* Head-to-Head */}
          <HeadToHeadSection encounters={liveDetailed.head_to_head} />

          {/* Strategic Advice */}
          <StrategicAdvicePanel tips={liveDetailed.strategic_advice} />
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold">LoL Tracker</h2>
          {seasons.length > 0 && (
            <select
              value={selectedSeasonId === 'all' ? '__all__' : (selectedSeasonId ?? '')}
              onChange={e => {
                const v = e.target.value;
                if (v === '') setSelectedSeasonId(null);
                else if (v === '__all__') setSelectedSeasonId('all');
                else setSelectedSeasonId(Number(v));
              }}
              className="bg-[#222] border border-[#333] rounded-lg px-3 py-1.5 text-sm text-gray-300 hover:border-cyan-500 focus:outline-none focus:border-cyan-500"
              title="Mudar de season"
            >
              <option value="">Season atual</option>
              <option value="__all__">Todas as seasons</option>
              {seasons.map(s => (
                <option key={s.id} value={s.id}>
                  {s.label}{s.active ? ' (atual)' : ''} — {s.total_games} jogos
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="flex items-center gap-2">
          {syncResult && (
            <span className="text-xs text-gray-400 mr-2">
              +{syncResult.imported} importadas
            </span>
          )}
          <button onClick={handleManualReset}
            className="flex items-center gap-2 px-3 py-2 bg-[#222] hover:bg-amber-700/40 rounded-xl text-sm text-gray-400 hover:text-amber-300"
            title="Forçar reset de season (fecha a atual e abre nova)">
            🗓️
          </button>
          <button onClick={() => setShowConfigModal(true)}
            className="flex items-center gap-2 px-3 py-2 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm text-gray-400 hover:text-white"
            title="Configurar Riot API">
            <Settings size={16} />
          </button>
          <button onClick={() => handleSync(undefined, true)} disabled={syncing}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white"
            title="Sincronizar games (season completa)">
            <RefreshCw size={16} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'A sincronizar...' : 'Sync'}
          </button>
        </div>
      </div>

      {/* Date Filter */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex gap-1 bg-[#111] rounded-xl p-1">
          {([['today', 'Hoje'], ['week', 'Semana'], ['month', 'Mês'], ['all', 'Todos']] as const).map(([key, label]) => (
            <button key={key} onClick={() => { setDateFilter(key); loadData(key); loadDetailedStats(key); }}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
                dateFilter === key ? 'bg-yellow-600 text-white' : 'text-gray-400 hover:text-white'
              }`}>
              {label}
            </button>
          ))}
        </div>
        <div className="flex gap-1 bg-[#111] rounded-xl p-1">
          <button onClick={() => { setActiveTab('main'); }}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'main' ? 'bg-yellow-600 text-white' : 'text-gray-400 hover:text-white'
            }`}>
            Games
          </button>
          <button onClick={() => { setActiveTab('stats'); if (!detailedStats) loadDetailedStats(); if (metaChampions.length === 0) loadMetaTierList(); if (!seasonStats) loadSeasonStats(); loadPredictionStats(); }}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'stats' ? 'bg-cyan-600 text-white' : 'text-gray-400 hover:text-white'
            }`}>
            📊 Estatísticas
          </button>
        </div>
      </div>

      {/* ══════════════ MAIN TAB ══════════════ */}
      {activeTab === 'main' && (<>

      {/* Stats Overview */}
      {stats && (() => {
        // When showing all games, use Riot API data for consistency with rank banner
        const useRiot = dateFilter === 'all' && rankInfo?.ranked;
        const displayWins = useRiot ? (rankInfo!.wins ?? stats.wins) : stats.wins;
        const displayLosses = useRiot ? (rankInfo!.losses ?? stats.losses) : stats.losses;
        const displayTotal = displayWins + displayLosses;
        const displayWinrate = useRiot ? (rankInfo!.winrate ?? stats.winrate) : stats.winrate;
        return (
        <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <p className="text-xs text-gray-500 mb-1">Total Games</p>
            <p className="text-2xl font-bold">{displayTotal}</p>
          </div>
          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
              <Trophy size={12} className="text-green-400" /> Vitórias
            </div>
            <p className="text-2xl font-bold text-green-400">{displayWins}</p>
          </div>
          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
              <Skull size={12} className="text-red-400" /> Derrotas
            </div>
            <p className="text-2xl font-bold text-red-400">{displayLosses}</p>
          </div>
          <div className="bg-[#161616] rounded-2xl p-5 border border-[#222]">
            <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
              <TrendingUp size={12} className="text-blue-400" /> Winrate
            </div>
            <p className={`text-2xl font-bold ${displayWinrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
              {displayWinrate}%
            </p>
          </div>
        </div>
        );
      })()}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Game History */}
        <div className="col-span-2 space-y-4">
          {Object.keys(gamesByDate).length === 0 ? (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-12 text-center">
              <Swords className="mx-auto mb-3 text-gray-600" size={40} />
              <p className="text-gray-500">Sem games registadas</p>
              <p className="text-gray-600 text-sm mt-1">Adiciona a tua primeira game!</p>
            </div>
          ) : (
            Object.entries(gamesByDate).map(([date, dayGames]) => {
              const wins = dayGames.filter(g => g.won).length;
              const losses = dayGames.length - wins;
              return (
                <div key={date} className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
                  <div className="flex items-center justify-between p-4 border-b border-[#222]">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium">{format(new Date(date), "d 'de' MMMM", { locale: pt })}</span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400">{wins}W</span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400">{losses}L</span>
                    </div>
                  </div>
                  <div className="divide-y divide-[#1a1a1a]">
                    {dayGames.map(game => (
                      <div key={game.id}>
                        <div className="flex items-center gap-4 p-4 hover:bg-white/5 cursor-pointer"
                          onClick={() => game.match_id && (selectedTimeline?.match_id === game.match_id ? setSelectedTimeline(null) : loadTimeline(game.match_id))}>
                        <div className={`w-10 h-10 rounded-xl flex items-center justify-center overflow-hidden ${
                          game.won ? 'ring-2 ring-green-500/50' : 'ring-2 ring-red-500/50'
                        }`}>
                          {game.champion_played ? (
                            <img
                              src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${game.champion_played}.png`}
                              alt={game.champion_played}
                              className="w-10 h-10 object-cover"
                              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                            />
                          ) : (
                            <span className="text-lg">{game.won ? '🏆' : '💀'}</span>
                          )}
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            {game.champion_played && (
                              <span className="text-sm font-medium text-blue-400">{game.champion_played}</span>
                            )}
                            {game.champion_against && (
                              <span className="text-xs text-gray-500">vs {game.champion_against}</span>
                            )}
                            {game.kills != null && game.deaths != null && game.assists != null && (
                              <span className="text-xs font-mono px-2 py-0.5 bg-[#222] rounded-full text-gray-300">
                                {game.kills}/{game.deaths}/{game.assists}
                              </span>
                            )}
                            {game.game_duration != null && (
                              <span className="text-xs text-gray-600">
                                {Math.floor(game.game_duration / 60)}:{String(game.game_duration % 60).padStart(2, '0')}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            {game.role && (
                              <span className="text-xs px-2 py-0.5 bg-[#222] rounded-full text-gray-400">{game.role}</span>
                            )}
                            {game.my_fault !== null && (
                              <span className={`text-xs px-2 py-0.5 rounded-full ${
                                game.my_fault ? 'bg-orange-500/20 text-orange-400' : 'bg-gray-500/20 text-gray-400'
                              }`}>
                                {game.my_fault ? 'Culpa minha' : 'Não foi culpa minha'}
                              </span>
                            )}
                          </div>
                          {game.notes && <p className="text-xs text-gray-600 mt-1">{game.notes}</p>}
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`text-sm font-bold ${game.won ? 'text-green-400' : 'text-red-400'}`}>
                            {game.won ? 'WIN' : 'LOSS'}
                          </span>
                          <button onClick={(e) => { e.stopPropagation(); handleDelete(game.id); }}
                            className="p-1 text-gray-600 hover:text-red-400">
                            <X size={14} />
                          </button>
                        </div>
                        </div>
                        {/* Timeline details */}
                        {selectedTimeline && game.match_id === selectedTimeline.match_id && (
                          <div className="px-4 pb-3 grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                            <div className="bg-[#111] rounded-lg p-2 text-center">
                              <p className="text-[10px] text-gray-500">Gold @15</p>
                              <p className="text-sm font-medium text-yellow-400">{selectedTimeline.gold_at_15 ? `${(selectedTimeline.gold_at_15 / 1000).toFixed(1)}k` : '—'}</p>
                            </div>
                            <div className="bg-[#111] rounded-lg p-2 text-center">
                              <p className="text-[10px] text-gray-500">Gold Diff @15</p>
                              <p className={`text-sm font-medium ${(selectedTimeline.gold_diff_at_15 || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                {selectedTimeline.gold_diff_at_15 != null ? `${selectedTimeline.gold_diff_at_15 > 0 ? '+' : ''}${(selectedTimeline.gold_diff_at_15 / 1000).toFixed(1)}k` : '—'}
                              </p>
                            </div>
                            <div className="bg-[#111] rounded-lg p-2 text-center">
                              <p className="text-[10px] text-gray-500">CS @15</p>
                              <p className="text-sm font-medium text-blue-400">{selectedTimeline.cs_at_15 ?? '—'}</p>
                            </div>
                            <div className="bg-[#111] rounded-lg p-2 text-center">
                              <p className="text-[10px] text-gray-500">First Blood</p>
                              <p className="text-sm font-medium">
                                {selectedTimeline.first_blood ? '🩸 Sim' : selectedTimeline.first_blood_victim ? '💀 Vítima' : '—'}
                              </p>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Champion Stats + Mastery */}
        <div className="space-y-4">
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-4 h-fit">
          <h3 className="text-sm font-medium text-gray-300 mb-4">Champion Stats</h3>
          {champStatsArr.length === 0 ? (
            <p className="text-xs text-gray-600">Sem dados</p>
          ) : (
            <div className="space-y-3">
              {champStatsArr.slice(0, 15).map(cs => (
                <div key={cs.name} className="flex items-center gap-3">
                  <span className="text-sm w-24 truncate">{cs.name}</span>
                  <div className="flex-1 h-2 bg-[#222] rounded-full overflow-hidden">
                    <div className="h-full rounded-full bg-gradient-to-r from-green-500 to-blue-500"
                      style={{ width: `${cs.winrate}%` }} />
                  </div>
                  <span className={`text-xs font-medium w-10 text-right ${cs.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                    {cs.winrate}%
                  </span>
                  <span className="text-xs text-gray-600 w-8">{cs.games}g</span>
                </div>
              ))}
            </div>
          )}
          </div>

          {/* Champion Mastery */}
          {mastery.length > 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-4">Champion Mastery</h3>
              <div className="space-y-2">
                {mastery.slice(0, 8).map((m, i) => (
                  <div key={m.champion_id} className="flex items-center gap-3">
                    <span className="text-xs text-gray-500 w-4">{i + 1}</span>
                    <span className="text-xs w-20 truncate">{m.champion_name}</span>
                    <span className="text-xs font-medium text-purple-400">Lv.{m.champion_level}</span>
                    <div className="flex-1">
                      <div className="h-1.5 bg-[#222] rounded-full overflow-hidden">
                        <div className="h-full rounded-full bg-gradient-to-r from-purple-500 to-pink-500"
                          style={{ width: `${Math.min(100, (m.champion_points / (mastery[0]?.champion_points || 1)) * 100)}%` }} />
                      </div>
                    </div>
                    <span className="text-xs text-gray-500 w-14 text-right">
                      {m.champion_points >= 1000000 ? `${(m.champion_points / 1000000).toFixed(1)}M` :
                       m.champion_points >= 1000 ? `${(m.champion_points / 1000).toFixed(0)}k` :
                       m.champion_points}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      </>)}

      {/* ══════════════ STATS TAB ══════════════ */}
      {activeTab === 'stats' && (
        <div className="space-y-6">

          {/* Champion Search Filter */}
          <div className="bg-[#161616] rounded-2xl border border-[#222] p-4">
            <div className="relative">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                placeholder="Pesquisar champion (jogado ou contra)..."
                value={statsChampFilter}
                onChange={e => setStatsChampFilter(e.target.value)}
                className="w-full bg-[#111] border border-[#333] rounded-xl pl-10 pr-10 py-2.5 text-sm focus:outline-none focus:border-cyan-500 placeholder-gray-600"
              />
              {statsChampFilter && (
                <button onClick={() => setStatsChampFilter('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white">
                  <X size={14} />
                </button>
              )}
            </div>
          </div>

          {/* Filtered Games List */}
          {statsChampFilter.trim() && filteredStatGames.length > 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
              <div className="flex items-center justify-between p-4 border-b border-[#222]">
                <h3 className="text-sm font-medium text-gray-300">
                  🎮 {statsChampMode === 'played' ? `Jogado com` : statsChampMode === 'against' ? `Jogado contra` : `Games com`} "{statsChampFilter}" ({filteredStatGames.length})
                </h3>
                <div className="flex items-center gap-3">
                  <div className="flex gap-1 bg-[#111] rounded-lg p-0.5">
                    {([['all', 'Todos'], ['played', 'Jogado'], ['against', 'Contra']] as const).map(([mode, label]) => (
                      <button key={mode} onClick={() => setStatsChampMode(mode)}
                        className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-all ${
                          statsChampMode === mode ? 'bg-cyan-600 text-white' : 'text-gray-400 hover:text-white'
                        }`}>
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400">
                      {filteredStatGames.filter(g => g.won).length}W
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400">
                      {filteredStatGames.filter(g => !g.won).length}L
                    </span>
                  </div>
                </div>
              </div>
              <div className="divide-y divide-[#1a1a1a] max-h-[400px] overflow-y-auto">
                {filteredStatGames.map(game => (
                  <div key={game.id} className="flex items-center gap-4 p-3 hover:bg-white/5">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center overflow-hidden ${
                      game.won ? 'ring-2 ring-green-500/50' : 'ring-2 ring-red-500/50'
                    }`}>
                      {game.champion_played ? (
                        <img
                          src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${game.champion_played}.png`}
                          alt={game.champion_played}
                          className="w-8 h-8 object-cover"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                        />
                      ) : (
                        <span className="text-sm">{game.won ? '🏆' : '💀'}</span>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-blue-400">{game.champion_played}</span>
                        {game.champion_against && (
                          <span className="text-xs text-gray-500">vs {game.champion_against}</span>
                        )}
                        {game.kills != null && game.deaths != null && game.assists != null && (
                          <span className="text-xs font-mono px-2 py-0.5 bg-[#222] rounded-full text-gray-300">
                            {game.kills}/{game.deaths}/{game.assists}
                          </span>
                        )}
                        {game.game_duration != null && (
                          <span className="text-xs text-gray-600">
                            {Math.floor(game.game_duration / 60)}:{String(game.game_duration % 60).padStart(2, '0')}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-gray-600">{format(new Date(game.date), "d MMM", { locale: pt })}</span>
                        {game.role && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-[#222] rounded-full text-gray-400">{game.role}</span>
                        )}
                      </div>
                    </div>
                    <span className={`text-xs font-bold ${game.won ? 'text-green-400' : 'text-red-400'}`}>
                      {game.won ? 'WIN' : 'LOSS'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {statsChampFilter.trim() && filteredStatGames.length === 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-6 text-center">
              <p className="text-gray-500 text-sm">Nenhuma game encontrada com "{statsChampFilter}"</p>
            </div>
          )}

          {/* Season Overview */}
          {detailedStats && detailedStats.total > 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
              <h3 className="text-sm font-medium text-gray-300 mb-4">📊 Visão Geral da Season</h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
                <div className="bg-[#111] rounded-xl p-3 text-center">
                  <p className="text-2xl font-bold">{detailedStats.total}</p>
                  <p className="text-[10px] text-gray-500">Total</p>
                </div>
                <div className="bg-[#111] rounded-xl p-3 text-center">
                  <p className="text-2xl font-bold text-green-400">{detailedStats.wins}</p>
                  <p className="text-[10px] text-gray-500">Vitórias</p>
                </div>
                <div className="bg-[#111] rounded-xl p-3 text-center">
                  <p className="text-2xl font-bold text-red-400">{detailedStats.losses}</p>
                  <p className="text-[10px] text-gray-500">Derrotas</p>
                </div>
                <div className="bg-[#111] rounded-xl p-3 text-center">
                  <p className={`text-2xl font-bold ${detailedStats.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                    {detailedStats.winrate}%
                  </p>
                  <p className="text-[10px] text-gray-500">Winrate</p>
                </div>
                <div className="bg-[#111] rounded-xl p-3 text-center">
                  <p className="text-2xl font-bold text-blue-400">{detailedStats.avg_kda}</p>
                  <p className="text-[10px] text-gray-500">KDA Médio</p>
                </div>
                <div className="bg-[#111] rounded-xl p-3 text-center">
                  <p className="text-2xl font-bold text-gray-300">{detailedStats.avg_duration}m</p>
                  <p className="text-[10px] text-gray-500">Duração Média</p>
                </div>
              </div>

              {/* KDA + Streaks + Game Length */}
              <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="bg-[#111] rounded-xl p-3">
                  <p className="text-[10px] text-gray-500 mb-1">KDA Médio</p>
                  <p className="text-sm font-medium">
                    <span className="text-green-400">{detailedStats.avg_kills}</span>
                    <span className="text-gray-500"> / </span>
                    <span className="text-red-400">{detailedStats.avg_deaths}</span>
                    <span className="text-gray-500"> / </span>
                    <span className="text-blue-400">{detailedStats.avg_assists}</span>
                  </p>
                </div>
                <div className="bg-[#111] rounded-xl p-3">
                  <p className="text-[10px] text-gray-500 mb-1">Streaks</p>
                  <p className="text-sm">
                    <span className="text-green-400 font-medium">{detailedStats.best_win_streak}W</span>
                    <span className="text-gray-500"> melhor · </span>
                    <span className="text-red-400 font-medium">{detailedStats.worst_loss_streak}L</span>
                    <span className="text-gray-500"> pior</span>
                  </p>
                  <p className="text-[10px] mt-0.5">
                    Atual: <span className={detailedStats.current_streak_type === 'win' ? 'text-green-400' : 'text-red-400'}>
                      {detailedStats.current_streak}{detailedStats.current_streak_type === 'win' ? 'W' : 'L'}
                    </span>
                  </p>
                </div>
                <div className="bg-[#111] rounded-xl p-3">
                  <p className="text-[10px] text-gray-500 mb-1">Últimas 20</p>
                  <p className="text-sm">
                    <span className={`font-medium ${detailedStats.last20_wr >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                      {detailedStats.last20_wr}% WR
                    </span>
                    <span className="text-gray-500 text-xs"> ({detailedStats.last20_count}g)</span>
                  </p>
                </div>
                <div className="bg-[#111] rounded-xl p-3">
                  <p className="text-[10px] text-gray-500 mb-1">Mais Jogado</p>
                  <p className="text-sm">
                    <span className="font-medium text-blue-400">{detailedStats.most_played_champ || '—'}</span>
                    <span className="text-gray-500 text-xs"> ({detailedStats.most_played_games}g)</span>
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Peak LP & Day-of-Week Performance */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {/* Peak LP & Ranking */}
            {(peakStats?.has_data || rankInfo?.ranked) && (
              <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
                <h3 className="text-sm font-medium text-gray-300 mb-3">
                  <Star size={14} className="inline text-yellow-400 mr-1" />
                  Peak & Ranking
                </h3>
                <div className="space-y-3">
                  {rankInfo?.ranked && (
                    <div className="bg-[#111] rounded-xl p-3 flex items-center justify-between">
                      <div>
                        <p className="text-[10px] text-gray-500">Rank Atual</p>
                        <p className="text-sm font-medium capitalize">
                          {rankInfo.tier?.toLowerCase()}{rankInfo.rank ? ` ${rankInfo.rank}` : ''}
                          <span className="text-yellow-400 ml-1.5">{rankInfo.lp} LP</span>
                        </p>
                      </div>
                      {rankInfo.hot_streak && <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400">🔥</span>}
                    </div>
                  )}
                  {peakStats?.peak_lp != null && (
                    <div className="bg-[#111] rounded-xl p-3">
                      <p className="text-[10px] text-gray-500">Peak LP</p>
                      <p className="text-sm font-medium">
                        <span className="capitalize">{peakStats.peak_tier?.toLowerCase()}</span>
                        <span className="text-yellow-400 ml-1.5">{peakStats.peak_lp} LP</span>
                        <span className="text-[10px] text-gray-600 ml-2">{peakStats.peak_date}</span>
                      </p>
                    </div>
                  )}
                  {rankPosition?.euw_rank && (
                    <div className="bg-[#111] rounded-xl p-3">
                      <p className="text-[10px] text-gray-500">Ranking EUW</p>
                      <p className="text-sm font-medium">
                        🇪🇺 <span className="text-yellow-400">#{rankPosition.euw_rank.toLocaleString()}</span>
                        {rankPosition.top_percent && <span className="text-green-400 text-xs ml-2">Top {rankPosition.top_percent}%</span>}
                      </p>
                    </div>
                  )}
                  {peakStats?.best_euw_rank && (
                    <div className="bg-[#111] rounded-xl p-3">
                      <p className="text-[10px] text-gray-500">Best Ranking EUW</p>
                      <p className="text-sm font-medium">
                        🇪🇺 <span className="text-yellow-400">#{peakStats.best_euw_rank.toLocaleString()}</span>
                        {peakStats.best_top_percent && <span className="text-green-400 text-xs ml-2">Top {peakStats.best_top_percent}%</span>}
                        <span className="text-[10px] text-gray-600 ml-2">{peakStats.best_rank_date}</span>
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Day of Week Performance */}
            {detailedStats?.dow_performance && (
              <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
                <h3 className="text-sm font-medium text-gray-300 mb-3">📆 Winrate por Dia da Semana</h3>
                <div className="space-y-1.5">
                  {detailedStats.dow_performance.filter((d: any) => d.games > 0).map((d: any) => (
                    <div key={d.day} className="flex items-center gap-3 text-xs">
                      <span className="text-gray-400 w-16 font-medium">{d.day}</span>
                      <div className="flex-1 h-2 bg-[#222] rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${d.winrate >= 50 ? 'bg-green-500' : 'bg-red-500'}`}
                          style={{ width: `${d.winrate}%` }} />
                      </div>
                      <span className={`font-medium w-10 text-right ${d.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                        {d.winrate}%
                      </span>
                      <span className="text-gray-500 w-16 text-right">{d.wins}W {d.losses}L</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ── NEW STATS: Hour Performance + Post-Streak WR ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {/* WR by Hour of Day */}
            {detailedStats?.hour_performance && detailedStats.hour_performance.some((h: any) => h.games > 0) && (
              <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
                <h3 className="text-sm font-medium text-gray-300 mb-3">🕐 Winrate por Hora do Dia</h3>
                <div className="space-y-1">
                  {detailedStats.hour_performance.filter((h: any) => h.games > 0).map((h: any) => (
                    <div key={h.hour} className="flex items-center gap-2 text-xs">
                      <span className="text-gray-400 w-10 font-mono">{String(h.hour).padStart(2, '0')}h</span>
                      <div className="flex-1 h-2 bg-[#222] rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${h.winrate >= 50 ? 'bg-green-500' : 'bg-red-500'}`}
                          style={{ width: `${h.winrate}%` }} />
                      </div>
                      <span className={`font-medium w-10 text-right ${h.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                        {h.winrate}%
                      </span>
                      <span className="text-gray-500 w-12 text-right">{h.games}g</span>
                    </div>
                  ))}
                </div>
                {!detailedStats.hour_performance.some((h: any) => h.games > 0) && (
                  <p className="text-xs text-gray-600 text-center py-2">Faz backfill para preencher dados de hora</p>
                )}
              </div>
            )}

            {/* Post-Streak WR + Side Performance + Champion Pool */}
            <div className="space-y-4">
              {/* WR Post-Streak */}
              {detailedStats?.post_streak_games > 0 && (
                <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
                  <h3 className="text-sm font-medium text-gray-300 mb-3">🔥 WR Pós-Streak (após 2+ derrotas)</h3>
                  <div className="flex items-center gap-4">
                    <div className={`text-2xl sm:text-3xl font-bold ${(detailedStats.post_streak_wr ?? 0) >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                      {detailedStats.post_streak_wr}%
                    </div>
                    <div className="text-xs text-gray-500">
                      <p>{detailedStats.post_streak_games} games após 2+ derrotas seguidas</p>
                      <p className="mt-1">{detailedStats.post_streak_wr != null && detailedStats.post_streak_wr >= 50
                        ? '✅ Recuperas bem após tilt'
                        : '⚠️ Cuidado com tilt — para depois de 2 losses seguidas'
                      }</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Blue/Red Side WR */}
              {detailedStats?.side_performance && Object.keys(detailedStats.side_performance).length > 0 && (
                <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
                  <h3 className="text-sm font-medium text-gray-300 mb-3">🔵🔴 Winrate por Lado</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {detailedStats.side_performance.blue && (
                      <div className="bg-[#111] rounded-xl p-3 text-center border border-blue-500/20">
                        <p className="text-[10px] text-blue-400 mb-1">Blue Side</p>
                        <p className={`text-xl font-bold ${detailedStats.side_performance.blue.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                          {detailedStats.side_performance.blue.winrate}%
                        </p>
                        <p className="text-[10px] text-gray-500">{detailedStats.side_performance.blue.wins}W {detailedStats.side_performance.blue.losses}L ({detailedStats.side_performance.blue.games}g)</p>
                      </div>
                    )}
                    {detailedStats.side_performance.red && (
                      <div className="bg-[#111] rounded-xl p-3 text-center border border-red-500/20">
                        <p className="text-[10px] text-red-400 mb-1">Red Side</p>
                        <p className={`text-xl font-bold ${detailedStats.side_performance.red.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                          {detailedStats.side_performance.red.winrate}%
                        </p>
                        <p className="text-[10px] text-gray-500">{detailedStats.side_performance.red.wins}W {detailedStats.side_performance.red.losses}L ({detailedStats.side_performance.red.games}g)</p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Champion Pool Depth */}
              {detailedStats?.champion_pool && (
                <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
                  <h3 className="text-sm font-medium text-gray-300 mb-3">🎮 Champion Pool</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mb-3">
                    <div className="bg-[#111] rounded-xl p-2.5 text-center">
                      <p className="text-xl font-bold text-cyan-400">{detailedStats.champion_pool.unique_champs}</p>
                      <p className="text-[10px] text-gray-500">Únicos</p>
                    </div>
                    <div className="bg-[#111] rounded-xl p-2.5 text-center">
                      <p className="text-xl font-bold text-yellow-400">{detailedStats.champion_pool.pool_80}</p>
                      <p className="text-[10px] text-gray-500">80% pick</p>
                    </div>
                    <div className="bg-[#111] rounded-xl p-2.5 text-center">
                      <p className="text-xl font-bold text-orange-400">{detailedStats.champion_pool.pool_90}</p>
                      <p className="text-[10px] text-gray-500">90% pick</p>
                    </div>
                  </div>
                  {detailedStats.champion_pool.top3?.length > 0 && (
                    <div className="space-y-1">
                      {detailedStats.champion_pool.top3.map((c: any, i: number) => (
                        <div key={c.champion} className="flex items-center gap-2 text-xs">
                          <span className="text-gray-500 w-4">{i === 0 ? '🥇' : i === 1 ? '🥈' : '🥉'}</span>
                          <span className="font-medium text-blue-400 w-20 truncate">{c.champion}</span>
                          <span className="text-gray-400">{c.games}g</span>
                          <span className={`ml-auto font-medium ${c.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>{c.winrate}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* ── WR by Game Duration ── */}
          {detailedStats?.duration_buckets && detailedStats.duration_buckets.some((d: any) => d.games > 0) && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
              <h3 className="text-sm font-medium text-gray-300 mb-3">⏱️ Winrate por Duração de Game</h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
                {detailedStats.duration_buckets.map((d: any) => (
                  <div key={d.label} className={`bg-[#111] rounded-xl p-3 text-center ${d.games === 0 ? 'opacity-40' : ''}`}>
                    <p className="text-[10px] text-gray-500 mb-1">{d.label}</p>
                    <p className={`text-lg font-bold ${d.games === 0 ? 'text-gray-600' : d.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                      {d.games > 0 ? `${d.winrate}%` : '—'}
                    </p>
                    <p className="text-[10px] text-gray-600">{d.games}g</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── LP Over Time Graph ── */}
          {detailedStats?.lp_history?.length > 1 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
              <h3 className="text-sm font-medium text-gray-300 mb-3">📈 LP ao Longo do Tempo</h3>
              {(() => {
                const data = detailedStats.lp_history;
                const lps = data.map((d: any) => d.total_lp);
                const minLp = Math.min(...lps);
                const maxLp = Math.max(...lps);
                const range = maxLp - minLp || 1;
                const h = 120;
                const w = 600;
                const points = data.map((d: any, i: number) => {
                  const x = (i / Math.max(data.length - 1, 1)) * w;
                  const y = h - ((d.total_lp - minLp) / range) * h;
                  return `${x},${y}`;
                }).join(' ');
                const areaPoints = `0,${h} ${points} ${w},${h}`;
                return (
                  <div className="relative">
                    <svg viewBox={`0 0 ${w} ${h + 20}`} className="w-full h-32" preserveAspectRatio="none">
                      <defs>
                        <linearGradient id="lpGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.3" />
                          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
                        </linearGradient>
                      </defs>
                      <polygon points={areaPoints} fill="url(#lpGrad)" />
                      <polyline points={points} fill="none" stroke="#22d3ee" strokeWidth="2" vectorEffect="non-scaling-stroke" />
                    </svg>
                    <div className="flex justify-between text-[10px] text-gray-500 mt-1">
                      <span>{data[0].date}</span>
                      <span className="text-cyan-400 font-medium">
                        {data[data.length - 1].tier} {data[data.length - 1].lp} LP
                      </span>
                      <span>{data[data.length - 1].date}</span>
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {/* Role Stats */}
            {detailedStats?.role_stats && (
              <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
                <h3 className="text-sm font-medium text-gray-300 mb-3">🎯 Estatísticas por Role</h3>
                <div className="space-y-2">
                  {Object.entries(detailedStats.role_stats)
                    .sort((a: any, b: any) => (b[1] as any).games - (a[1] as any).games)
                    .map(([role, s]: [string, any]) => (
                    <div key={role} className="flex items-center gap-3 bg-[#111] rounded-lg p-2.5">
                      <span className="text-xs font-medium w-16 capitalize">{role}</span>
                      <div className="flex-1 h-2 bg-[#222] rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${s.winrate >= 50 ? 'bg-green-500' : 'bg-red-500'}`}
                          style={{ width: `${s.winrate}%` }} />
                      </div>
                      <span className={`text-xs font-medium w-12 text-right ${s.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                        {s.winrate}%
                      </span>
                      <span className="text-xs text-gray-500 w-10">{s.games}g</span>
                      <span className="text-[10px] text-gray-600 w-14">KDA {s.avg_kda}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Most Faced Champions */}
            {filteredDetailedStats?.most_faced?.length > 0 && (
              <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
                <h3 className="text-sm font-medium text-gray-300 mb-3">⚔️ Champions Mais Enfrentados</h3>
                <div className="space-y-1.5">
                  {filteredDetailedStats.most_faced.slice(0, 10).map((c: any, i: number) => (
                    <div key={c.champion} className="flex items-center gap-2 text-xs">
                      <span className="text-gray-500 w-4">{i + 1}</span>
                      <div className="w-6 h-6 rounded overflow-hidden bg-[#222] flex-shrink-0">
                        <img
                          src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${c.champion}.png`}
                          alt={c.champion}
                          className="w-6 h-6 object-cover"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                        />
                      </div>
                      <span className="w-24 truncate font-medium">{c.champion}</span>
                      <div className="flex-1 h-1.5 bg-[#222] rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${c.winrate >= 50 ? 'bg-green-500' : 'bg-red-500'}`}
                          style={{ width: `${c.winrate}%` }} />
                      </div>
                      <span className={`font-medium w-10 text-right ${c.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                        {c.winrate}%
                      </span>
                      <span className="text-gray-500 w-16 text-right">{c.wins}W {c.losses}L</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Champion Performance Table */}
          {filteredDetailedStats?.champion_stats?.length > 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
              <h3 className="text-sm font-medium text-gray-300 mb-3">🏆 Performance por Champion</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 border-b border-[#222]">
                      <th className="text-left py-2 px-2">#</th>
                      <th className="text-left py-2 px-2">Champion</th>
                      <th className="text-center py-2 px-2">Games</th>
                      <th className="text-center py-2 px-2">WR</th>
                      <th className="text-center py-2 px-2">W/L</th>
                      <th className="text-center py-2 px-2">KDA</th>
                      <th className="text-center py-2 px-2">Avg K/D/A</th>
                      <th className="text-center py-2 px-2">Duração</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1a1a1a]">
                    {filteredDetailedStats.champion_stats.map((c: any, i: number) => (
                      <tr key={c.champion} className="hover:bg-white/5">
                        <td className="py-2 px-2 text-gray-500">{i + 1}</td>
                        <td className="py-2 px-2">
                          <div className="flex items-center gap-2">
                            <div className="w-6 h-6 rounded overflow-hidden bg-[#222] flex-shrink-0">
                              <img
                                src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${c.champion}.png`}
                                alt={c.champion}
                                className="w-6 h-6 object-cover"
                                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                              />
                            </div>
                            <span className="font-medium">{c.champion}</span>
                          </div>
                        </td>
                        <td className="text-center py-2 px-2">{c.games}</td>
                        <td className={`text-center py-2 px-2 font-medium ${c.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                          {c.winrate}%
                        </td>
                        <td className="text-center py-2 px-2">
                          <span className="text-green-400">{c.wins}</span>/<span className="text-red-400">{c.losses}</span>
                        </td>
                        <td className={`text-center py-2 px-2 font-medium ${c.avg_kda >= 3 ? 'text-green-400' : c.avg_kda >= 2 ? 'text-yellow-400' : 'text-red-400'}`}>
                          {c.avg_kda}
                        </td>
                        <td className="text-center py-2 px-2 text-gray-400">
                          {c.avg_kills}/{c.avg_deaths}/{c.avg_assists}
                        </td>
                        <td className="text-center py-2 px-2 text-gray-500">{c.avg_duration}m</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Daily Performance — by month */}
          {detailedStats?.daily_performance?.length > 0 && (
            <div className="bg-[#161616] rounded-2xl border border-[#222] p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-gray-300">📅 Performance Diária</h3>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      const idx = availableMonths.indexOf(perfMonth);
                      if (idx < availableMonths.length - 1) setPerfMonth(availableMonths[idx + 1]);
                    }}
                    disabled={availableMonths.indexOf(perfMonth) >= availableMonths.length - 1}
                    className="p-1 rounded hover:bg-[#222] disabled:opacity-30">
                    <ChevronLeft size={14} />
                  </button>
                  <span className="text-xs font-medium text-gray-300 w-20 text-center">
                    {format(new Date(perfMonth + '-01'), 'MMMM yyyy', { locale: pt })}
                  </span>
                  <button
                    onClick={() => {
                      const idx = availableMonths.indexOf(perfMonth);
                      if (idx > 0) setPerfMonth(availableMonths[idx - 1]);
                    }}
                    disabled={availableMonths.indexOf(perfMonth) <= 0}
                    className="p-1 rounded hover:bg-[#222] disabled:opacity-30">
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
              {filteredDailyPerf.length === 0 ? (
                <p className="text-xs text-gray-600 text-center py-4">Sem games neste mês</p>
              ) : (
                <div className="space-y-1">
                  {filteredDailyPerf.map((d: any) => (
                    <div key={d.date} className="flex items-center gap-3 text-xs">
                      <span className="text-gray-500 w-24">{format(new Date(d.date), "d MMM", { locale: pt })}</span>
                      <div className="flex gap-0.5">
                        {Array.from({ length: d.wins }, (_, i) => (
                          <div key={`w${i}`} className="w-3 h-3 rounded-sm bg-green-500/60" />
                        ))}
                        {Array.from({ length: d.losses }, (_, i) => (
                          <div key={`l${i}`} className="w-3 h-3 rounded-sm bg-red-500/60" />
                        ))}
                      </div>
                      <span className={`ml-auto font-medium ${d.winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                        {d.winrate}%
                      </span>
                      <span className="text-gray-600 w-16 text-right">{d.wins}W {d.losses}L</span>
                    </div>
                  ))}
                </div>
              )}
              {/* Month summary */}
              {filteredDailyPerf.length > 0 && (() => {
                const mWins = filteredDailyPerf.reduce((s: number, d: any) => s + d.wins, 0);
                const mLosses = filteredDailyPerf.reduce((s: number, d: any) => s + d.losses, 0);
                const mTotal = mWins + mLosses;
                const mWr = mTotal > 0 ? Math.round(mWins / mTotal * 100) : 0;
                return (
                  <div className="flex items-center justify-between mt-3 pt-3 border-t border-[#222] text-xs">
                    <span className="text-gray-500">{mTotal} games neste mês</span>
                    <span className={`font-medium ${mWr >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                      {mWins}W {mLosses}L — {mWr}% WR
                    </span>
                  </div>
                );
              })()}
            </div>
          )}

          {/* Meta Tier List */}
          <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
            <div className="px-4 py-3 border-b border-[#222]">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium">🌍 Meta Tier List — Jungle Master+</h3>
                  <p className="text-xs text-gray-500 mt-0.5">{metaChampions.length} champions</p>
                </div>
              </div>
              {/* Source buttons */}
              <div className="flex gap-1.5 mt-2 flex-wrap">
                {[
                  { key: 'all', label: 'Todos' },
                  { key: 'lolalytics', label: 'LoLalytics' },
                  { key: 'ugg', label: 'u.gg' },
                  { key: 'opgg', label: 'op.gg' },
                  { key: 'leagueofgraphs', label: 'LoG' },
                ].map(s => (
                  <button
                    key={s.key}
                    onClick={() => {
                      setMetaSource(s.key);
                      loadMetaTierList(s.key);
                    }}
                    className={`px-2.5 py-1 rounded text-[10px] font-medium transition-all ${
                      metaSource === s.key
                        ? 'bg-blue-600 text-white'
                        : metaAvailableSources.includes(s.key) || s.key === 'all'
                          ? 'bg-[#222] text-gray-400 hover:bg-[#2a2a2a]'
                          : 'bg-[#1a1a1a] text-gray-600 cursor-not-allowed'
                    }`}
                    disabled={s.key !== 'all' && !metaAvailableSources.includes(s.key)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              {/* Sort & Search */}
              <div className="flex gap-2 mt-2 flex-wrap items-center">
                <input
                  type="text"
                  placeholder="🔍 Champion..."
                  value={metaSearch}
                  onChange={e => setMetaSearch(e.target.value)}
                  className="bg-[#222] border border-[#333] rounded px-2 py-1 text-[11px] w-28 focus:outline-none focus:border-blue-500"
                />
                <span className="text-[10px] text-gray-500">Ordenar:</span>
                {[
                  { key: 'tier', label: 'Tier' },
                  { key: 'wr', label: 'Win Rate' },
                  { key: 'games', label: 'Games' },
                  { key: 'pr', label: 'Pick Rate' },
                  { key: 'br', label: 'Ban Rate' },
                ].map(s => (
                  <button
                    key={s.key}
                    onClick={() => {
                      if (metaSort === s.key) {
                        setMetaSortDir(d => d === 'asc' ? 'desc' : 'asc');
                      } else {
                        setMetaSort(s.key);
                        setMetaSortDir(s.key === 'tier' ? 'asc' : 'desc');
                      }
                    }}
                    className={`px-2 py-1 rounded text-[10px] font-medium transition-all ${
                      metaSort === s.key ? 'bg-blue-600 text-white' : 'bg-[#222] text-gray-400 hover:bg-[#2a2a2a]'
                    }`}
                  >
                    {s.label} {metaSort === s.key ? (metaSortDir === 'asc' ? '↑' : '↓') : ''}
                  </button>
                ))}
              </div>
            </div>
            {metaChampions.length === 0 ? (
              <div className="p-8 text-center text-sm">
                {metaLoading ? (
                  <div className="flex items-center justify-center gap-2 text-gray-500">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg>
                    A carregar dados meta...
                  </div>
                ) : metaError ? (
                  <div className="space-y-2">
                    <p className="text-red-400">Não foi possível carregar os dados meta</p>
                    <button onClick={() => loadMetaTierList()} className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs rounded-lg transition-colors">
                      Tentar novamente
                    </button>
                  </div>
                ) : (
                  <span className="text-gray-500">A carregar dados meta...</span>
                )}
              </div>
            ) : (() => {
              const getTierLabel = (t: number) => t <= 1 ? 'S+' : t <= 3 ? 'S' : t <= 5 ? 'A' : t <= 8 ? 'B' : t <= 11 ? 'C' : 'D';
              const filtered = metaChampions
                .filter(c => {
                  if (metaSearch && !(c.ddragon_key || c.champion || '').toLowerCase().includes(metaSearch.toLowerCase())) return false;
                  return true;
                })
                .sort((a, b) => {
                  const dir = metaSortDir === 'asc' ? 1 : -1;
                  if (metaSort === 'tier') {
                    const t = ((a.tier ?? 99) - (b.tier ?? 99)) * dir;
                    return t !== 0 ? t : (a.rank || 999) - (b.rank || 999);
                  }
                  if (metaSort === 'wr') return ((a.wr || 0) - (b.wr || 0)) * dir;
                  if (metaSort === 'games') return ((a.games || 0) - (b.games || 0)) * dir;
                  if (metaSort === 'pr') return ((a.pr || 0) - (b.pr || 0)) * dir;
                  if (metaSort === 'br') return ((a.br || 0) - (b.br || 0)) * dir;
                  return 0;
                });
              return filtered.length === 0 ? (
                <div className="p-6 text-center text-gray-500 text-sm">Nenhum champion encontrado</div>
              ) : (
                <div className="divide-y divide-[#1a1a1a] max-h-[500px] overflow-y-auto">
                  {filtered.map((c, i) => (
                  <div key={c.champion || i} className="flex items-center gap-3 px-4 py-2 hover:bg-white/5">
                    <span className="text-xs text-gray-500 w-6 text-right">#{c.rank || i + 1}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                      c.tier <= 1 ? 'bg-red-500/20 text-red-400' :
                      c.tier <= 3 ? 'bg-orange-500/20 text-orange-400' :
                      c.tier <= 5 ? 'bg-yellow-500/20 text-yellow-400' :
                      c.tier <= 8 ? 'bg-green-500/20 text-green-400' :
                      c.tier <= 11 ? 'bg-blue-500/20 text-blue-400' :
                      'bg-gray-500/20 text-gray-400'
                    }`}>{
                      c.tier <= 1 ? 'S+' :
                      c.tier <= 3 ? 'S' :
                      c.tier <= 5 ? 'A' :
                      c.tier <= 8 ? 'B' :
                      c.tier <= 11 ? 'C' :
                      'D'
                    }</span>
                    <div className="w-8 h-8 rounded-lg overflow-hidden bg-[#222] flex-shrink-0">
                      <img
                        src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${c.ddragon_key || c.champion}.png`}
                        alt={c.champion}
                        className="w-8 h-8 object-cover"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                      />
                    </div>
                    <span className="text-sm font-medium w-28 truncate">{c.ddragon_key || c.champion}</span>
                    <div className="flex items-center gap-4 flex-1">
                      <div className="text-center">
                        <p className={`text-xs font-medium ${(c.wr || 0) >= 52 ? 'text-green-400' : (c.wr || 0) >= 50 ? 'text-gray-300' : 'text-red-400'}`}>
                          {c.wr?.toFixed(1)}%
                        </p>
                        <p className="text-[9px] text-gray-600">WR</p>
                      </div>
                      <div className="text-center">
                        <p className="text-xs text-gray-300">{c.pr?.toFixed(1)}%</p>
                        <p className="text-[9px] text-gray-600">PR</p>
                      </div>
                      <div className="text-center">
                        <p className="text-xs text-gray-300">{c.br?.toFixed(1)}%</p>
                        <p className="text-[9px] text-gray-600">BR</p>
                      </div>
                      <div className="text-center">
                        <p className="text-xs text-gray-500">{c.games ? c.games.toLocaleString() : '—'}</p>
                        <p className="text-[9px] text-gray-600">Games</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              );
            })()}
          </div>

          {/* AI Prediction Stats */}
          <AIPredictionPanel stats={predStats} history={predHistory} calibration={predCalibration} onResolve={async () => {
            await lolApi.resolvePredictions();
            loadPredictionStats();
          }} />

        </div>
      )}

      {/* Riot API Config Modal */}
      {showConfigModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowConfigModal(false)}>
          <div className="bg-[#1a1a1a] rounded-2xl p-6 max-w-[90vw] w-[460px] border border-[#333]"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">Configurar Riot API</h3>
              <button onClick={() => setShowConfigModal(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 block mb-1">Game Name</label>
                  <input type="text" value={riotGameName}
                    onChange={e => setRiotGameName(e.target.value)}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500" />
                </div>
                <div>
                  <label className="text-xs text-gray-500 block mb-1">Tag Line</label>
                  <input type="text" value={riotTagLine}
                    onChange={e => setRiotTagLine(e.target.value)}
                    className="w-full bg-[#222] border border-[#333] rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500" />
                </div>
              </div>

              <div className="bg-[#111] rounded-xl p-3 text-xs text-gray-500">
                Conta: <span className="text-white">{riotGameName}#{riotTagLine}</span>
                <br />
                <span className="text-green-500 mt-1 block">Riot API configurada — sincroniza os jogos de hoje automaticamente</span>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <div className="flex-1" />
              <button onClick={() => setShowConfigModal(false)}
                className="px-4 py-2.5 bg-[#222] hover:bg-[#2a2a2a] rounded-xl text-sm">Cancelar</button>
              <button onClick={handleSaveConfig}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl text-sm font-medium">
                Guardar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Swords({ className, size }: { className?: string; size: number }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5" />
      <line x1="13" x2="19" y1="19" y2="13" />
      <line x1="16" x2="20" y1="16" y2="20" />
      <line x1="19" x2="21" y1="21" y2="19" />
      <polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5" />
      <line x1="5" x2="9" y1="14" y2="18" />
      <line x1="7" x2="4" y1="17" y2="20" />
      <line x1="3" x2="5" y1="19" y2="21" />
    </svg>
  );
}

const TIER_COLORS: Record<string, string> = {
  IRON: 'text-gray-500', BRONZE: 'text-amber-700', SILVER: 'text-gray-400',
  GOLD: 'text-yellow-400', PLATINUM: 'text-teal-400', EMERALD: 'text-emerald-400',
  DIAMOND: 'text-cyan-400', MASTER: 'text-purple-400', GRANDMASTER: 'text-red-400',
  CHALLENGER: 'text-yellow-300',
};

const TIER_SHORT: Record<string, string> = {
  IRON: 'I', BRONZE: 'B', SILVER: 'S', GOLD: 'G', PLATINUM: 'P',
  EMERALD: 'E', DIAMOND: 'D', MASTER: 'M', GRANDMASTER: 'GM', CHALLENGER: 'C',
};

const TIER_BG: Record<string, string> = {
  IRON: 'bg-gray-500/10', BRONZE: 'bg-amber-700/10', SILVER: 'bg-gray-400/10',
  GOLD: 'bg-yellow-400/10', PLATINUM: 'bg-teal-400/10', EMERALD: 'bg-emerald-400/10',
  DIAMOND: 'bg-cyan-400/10', MASTER: 'bg-purple-400/10', GRANDMASTER: 'bg-red-400/10',
  CHALLENGER: 'bg-yellow-300/10',
};

const SPELL_MAP: Record<number, string> = {
  1: 'SummonerBoost', 3: 'SummonerExhaust', 4: 'SummonerFlash',
  6: 'SummonerHaste', 7: 'SummonerHeal', 11: 'SummonerSmite',
  12: 'SummonerTeleport', 14: 'SummonerDot', 21: 'SummonerBarrier',
  32: 'SummonerSnowball',
};

const ROLE_LABELS: Record<string, string> = {
  top: 'Top', jungle: 'Jungle', mid: 'Mid', adc: 'ADC', support: 'Support',
};

const TAG_COLORS: Record<string, { bg: string; text: string }> = {
  orange: { bg: 'bg-orange-500/15', text: 'text-orange-400' },
  green: { bg: 'bg-green-500/15', text: 'text-green-400' },
  red: { bg: 'bg-red-500/15', text: 'text-red-400' },
  purple: { bg: 'bg-purple-500/15', text: 'text-purple-400' },
  blue: { bg: 'bg-blue-500/15', text: 'text-blue-400' },
  yellow: { bg: 'bg-yellow-500/15', text: 'text-yellow-400' },
  cyan: { bg: 'bg-cyan-500/15', text: 'text-cyan-400' },
  gray: { bg: 'bg-gray-500/15', text: 'text-gray-400' },
};

function LivePlayerRow({ player, ddVersion }: { player: LivePlayer; ddVersion: string }) {
  const r = player.rank;
  const tierColor = r ? (TIER_COLORS[r.tier] || 'text-gray-400') : 'text-gray-600';
  const tierShort = r ? (TIER_SHORT[r.tier] || r.tier?.[0]) : '';
  const tierBg = r ? (TIER_BG[r.tier] || 'bg-[#1a1a1a]') : 'bg-[#1a1a1a]';
  const cs = player.champion_stats;

  const masteryK = player.mastery_points >= 1000000
    ? `${(player.mastery_points / 1000000).toFixed(1)}M`
    : player.mastery_points >= 1000
    ? `${Math.round(player.mastery_points / 1000)}k`
    : String(player.mastery_points);

  const seasonTotal = r ? r.wins + r.losses : 0;

  return (
    <div className={`px-3 py-2.5 ${player.is_me ? 'bg-blue-500/8 border-l-2 border-blue-500' : 'hover:bg-[#111]'} transition-colors`}>
      {/* Row 1: Champion, Spells, Name, Rank, Season */}
      <div className="flex items-center gap-2">
        {/* Champion icon + mastery badge */}
        <div className="relative shrink-0">
          <img
            src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${player.champion_name}.png`}
            alt={player.champion_name}
            className="w-10 h-10 rounded-lg border border-[#333]"
            onError={(e) => { (e.target as HTMLImageElement).src = `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/Aatrox.png`; }}
          />
          {player.mastery_level >= 4 && (
            <span className={`absolute -bottom-1 -right-1 text-[8px] font-bold rounded px-0.5 ${
              player.mastery_level >= 7 ? 'bg-purple-600 text-white' :
              player.mastery_level >= 5 ? 'bg-red-600 text-white' :
              'bg-gray-600 text-gray-200'
            }`}>
              M{player.mastery_level}
            </span>
          )}
        </div>

        {/* Summoner spells */}
        <div className="flex flex-col gap-0.5 shrink-0">
          <img
            src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/spell/${SPELL_MAP[player.spell1] || 'SummonerFlash'}.png`}
            className="w-4 h-4 rounded"
            alt=""
          />
          <img
            src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/spell/${SPELL_MAP[player.spell2] || 'SummonerFlash'}.png`}
            className="w-4 h-4 rounded"
            alt=""
          />
        </div>

        {/* Name + Champion */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1">
            <span className={`text-xs font-semibold truncate ${player.is_me ? 'text-blue-300' : 'text-white'}`}>
              {player.summoner_name}
            </span>
            {player.is_me && <span className="text-[8px] font-bold bg-blue-500/30 text-blue-300 rounded px-1 py-px">TU</span>}
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-gray-500">{player.champion_name}</span>
            {player.mastery_points > 0 && (
              <span className="text-[9px] text-yellow-600">{masteryK}</span>
            )}
          </div>
        </div>

        {/* Rank badge */}
        <div className={`text-right shrink-0 rounded-lg px-2 py-1 ${tierBg}`}>
          {r ? (
            <>
              <p className={`text-[11px] font-bold ${tierColor} leading-tight`}>
                {tierShort}{r.tier === 'MASTER' || r.tier === 'GRANDMASTER' || r.tier === 'CHALLENGER' ? '' : ` ${r.rank}`} {r.lp}LP
              </p>
              <p className={`text-[9px] leading-tight ${r.winrate >= 52 ? 'text-green-400' : r.winrate >= 48 ? 'text-gray-500' : 'text-red-400'}`}>
                {r.wins}W {r.losses}L — {r.winrate}%
              </p>
            </>
          ) : (
            <p className="text-[10px] text-gray-600">Unranked</p>
          )}
        </div>

        {/* Recent form dots */}
        {player.recent_games?.results?.length > 0 && (
          <div className="flex flex-col gap-px shrink-0 ml-1">
            <div className="flex gap-0.5">
              {player.recent_games.results.slice(0, 5).map((won, i) => (
                <div key={i} className={`w-2 h-2 rounded-full ${won ? 'bg-green-500' : 'bg-red-500'}`} />
              ))}
            </div>
            <span className="text-[8px] text-gray-600 text-center">
              {player.recent_games.results.filter(Boolean).length}W-{player.recent_games.results.filter(r => !r).length}L
            </span>
          </div>
        )}
      </div>

      {/* Row 2: Champion stats + Role + Tags */}
      <div className="flex items-center gap-2 mt-1.5 ml-[52px]">
        {/* Champion specific stats */}
        {cs ? (
          <div className="flex items-center gap-2 text-[10px]">
            <span className={`font-semibold ${cs.winrate >= 55 ? 'text-green-400' : cs.winrate >= 45 ? 'text-gray-300' : 'text-red-400'}`}>
              {cs.winrate}% WR
            </span>
            <span className="text-gray-500">{cs.games}G</span>
            <span className="text-gray-400">{cs.avg_kills}/{cs.avg_deaths}/{cs.avg_assists}</span>
            <span className={`font-medium ${cs.avg_kda >= 3 ? 'text-green-400' : cs.avg_kda >= 2 ? 'text-gray-300' : 'text-red-400'}`}>
              {cs.avg_kda} KDA
            </span>
          </div>
        ) : (
          <span className="text-[10px] text-gray-600 italic">Sem jogos recentes neste campeão</span>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Role */}
        {player.role && (
          <span className="text-[9px] text-gray-500 bg-[#1a1a1a] rounded px-1.5 py-0.5">
            {ROLE_LABELS[player.role] || player.role}
            {player.role_games > 0 && <span className="text-gray-600 ml-0.5">({player.role_games}G)</span>}
          </span>
        )}
      </div>

      {/* Row 3: Tags + Mental State + Rank Trajectory + Champion Pool */}
      <div className="flex flex-wrap gap-1 mt-1 ml-[52px]">
        {/* Mental state badge */}
        {player.mental_state && player.mental_state.state !== 'neutral' && (
          <span className={`text-[8px] font-medium px-1.5 py-0.5 rounded ${
            TAG_COLORS[player.mental_state.color]?.bg || 'bg-gray-500/15'
          } ${TAG_COLORS[player.mental_state.color]?.text || 'text-gray-400'}`}>
            {player.mental_state.marathon_label || player.mental_state.label}
          </span>
        )}
        {/* Rank trajectory badge */}
        {player.rank_trajectory && player.rank_trajectory.trajectory !== 'stable' && player.rank_trajectory.trajectory !== 'unknown' && (
          <span className={`text-[8px] font-medium px-1.5 py-0.5 rounded ${
            TAG_COLORS[player.rank_trajectory.color || 'gray']?.bg || 'bg-gray-500/15'
          } ${TAG_COLORS[player.rank_trajectory.color || 'gray']?.text || 'text-gray-400'}`}
            title={player.rank_trajectory.detail || ''}>
            {player.rank_trajectory.label}
          </span>
        )}
        {/* Champion pool badge */}
        {player.champion_pool && player.champion_pool.category !== 'versatile' && (
          <span className={`text-[8px] font-medium px-1.5 py-0.5 rounded ${
            player.champion_pool.category === 'otp' ? 'bg-purple-500/15 text-purple-400' : 'bg-blue-500/15 text-blue-400'
          }`} title={`${player.champion_pool.unique_champions} campeões jogados: ${player.champion_pool.champions_played.join(', ')}`}>
            🎮 {player.champion_pool.label} ({player.champion_pool.unique_champions})
          </span>
        )}
        {/* Existing tags */}
        {player.tags?.map((tag, i) => {
          const colors = TAG_COLORS[tag.color] || TAG_COLORS.gray;
          return (
            <span key={i} className={`text-[8px] font-medium px-1.5 py-0.5 rounded ${colors.bg} ${colors.text}`}>
              {tag.text}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function TeamStatsBar({ stats, label, color }: { stats?: LiveTeamStats; label: string; color: 'blue' | 'red' }) {
  if (!stats) return null;
  const accent = color === 'blue' ? 'text-blue-400' : 'text-red-400';
  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-[#0d0d0d] border-t border-[#222]">
      <span className={`text-[9px] font-bold uppercase tracking-wider ${accent}`}>{label}</span>
      {stats.avg_rank_str && (
        <span className="text-[10px] text-gray-300">
          Avg: <span className="font-semibold">{stats.avg_rank_str}</span>
        </span>
      )}
      {stats.avg_winrate != null && (
        <span className={`text-[10px] ${stats.avg_winrate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
          {stats.avg_winrate}% WR
        </span>
      )}
      {stats.avg_kda != null && (
        <span className="text-[10px] text-gray-400">
          {stats.avg_kda} KDA
        </span>
      )}
      {stats.avg_gold_per_min != null && (
        <span className="text-[10px] text-yellow-500/70">
          {stats.avg_gold_per_min} Gold/min
        </span>
      )}
      {stats.avg_damage_per_min != null && (
        <span className="text-[10px] text-orange-400/70">
          {stats.avg_damage_per_min} DMG/min
        </span>
      )}
      {stats.avg_vision_per_min != null && (
        <span className="text-[10px] text-purple-400/70">
          {stats.avg_vision_per_min} Vis/min
        </span>
      )}
    </div>
  );
}

/* ── Personal Matchup Panel (In-Game) ────────────────────────── */
interface PersonalMatchupData {
  vs_enemy_all?: { wins: number; losses: number; games: number; winrate: number };
  my_champ_vs_enemy?: { wins: number; losses: number; games: number; winrate: number };
  best_picks?: Array<{ champion: string; wins: number; losses: number; games: number; winrate: number }>;
}

function PersonalMatchupPanel({
  personalMatchups,
  enemyTeam,
  myTeam,
  ddVersion,
}: {
  personalMatchups?: Record<string, PersonalMatchupData>;
  enemyTeam?: Array<{ champion_name?: string; role?: string }>;
  myTeam?: Array<{ champion_name?: string; is_me?: boolean }>;
  ddVersion: string;
}) {
  if (!personalMatchups || !Object.keys(personalMatchups).length) return null;

  const myChamp = myTeam?.find(p => p.is_me)?.champion_name;

  return (
    <div className="border-t border-[#1a1a1a]">
      <div className="px-4 py-2.5 bg-[#0a0a0a]">
        <span className="text-[10px] font-bold uppercase tracking-wider text-purple-400">📊 O Teu Histórico vs Inimigos</span>
      </div>
      <div className="divide-y divide-[#151515]">
        {enemyTeam?.filter(p => p.champion_name && personalMatchups[p.champion_name]).map(p => {
          const enemy = p.champion_name!;
          const data = personalMatchups[enemy];
          const specific = data.my_champ_vs_enemy;
          const all = data.vs_enemy_all;

          return (
            <div key={enemy} className="px-4 py-2.5 hover:bg-[#0f0f0f] transition-colors">
              <div className="flex items-center gap-3">
                {/* Enemy champion icon */}
                <div className="flex items-center gap-2 w-32 shrink-0">
                  <img
                    src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${enemy}.png`}
                    className="w-7 h-7 rounded-lg border border-[#333]"
                    alt={enemy}
                    onError={(e) => { (e.target as HTMLImageElement).src = `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/Aatrox.png`; }}
                  />
                  <div>
                    <p className="text-[10px] text-red-300 font-medium">{enemy}</p>
                    {p.role && <p className="text-[7px] text-gray-600 uppercase">{p.role}</p>}
                  </div>
                </div>

                <div className="flex-1 flex items-center gap-4 flex-wrap">
                  {/* Specific matchup: my champ vs this enemy */}
                  {specific && myChamp && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-[8px] text-gray-500">{myChamp} vs {enemy}:</span>
                      <span className={`text-[11px] font-bold ${
                        specific.winrate >= 60 ? 'text-green-400' :
                        specific.winrate >= 50 ? 'text-blue-300' :
                        'text-red-400'
                      }`}>
                        {specific.winrate}%
                      </span>
                      <span className="text-[8px] text-gray-600">
                        ({specific.wins}W {specific.losses}L)
                      </span>
                    </div>
                  )}

                  {/* Overall vs this enemy (any champion) */}
                  {all && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-[8px] text-gray-500">Total vs {enemy}:</span>
                      <span className={`text-[11px] font-bold ${
                        all.winrate >= 60 ? 'text-green-400' :
                        all.winrate >= 50 ? 'text-blue-300' :
                        'text-red-400'
                      }`}>
                        {all.winrate}%
                      </span>
                      <span className="text-[8px] text-gray-600">
                        ({all.wins}W {all.losses}L)
                      </span>
                    </div>
                  )}

                  {/* Best picks hint */}
                  {data.best_picks && data.best_picks.length > 0 && !specific && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-[8px] text-gray-500">Melhor:</span>
                      {data.best_picks.slice(0, 2).map(bp => (
                        <span key={bp.champion} className={`text-[9px] px-1 py-px rounded ${
                          bp.winrate >= 60 ? 'bg-green-500/10 text-green-400' :
                          bp.winrate >= 50 ? 'bg-gray-500/10 text-gray-300' :
                          'bg-red-500/10 text-red-400'
                        }`}>
                          {bp.champion} {bp.winrate}% ({bp.games}g)
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* Enemies with no matchup data */}
        {enemyTeam?.filter(p => p.champion_name && !personalMatchups[p.champion_name]).map(p => (
          <div key={p.champion_name} className="px-4 py-2 hover:bg-[#0f0f0f]">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 w-32">
                <img
                  src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${p.champion_name}.png`}
                  className="w-7 h-7 rounded-lg border border-[#333] opacity-40"
                  alt={p.champion_name || ''}
                  onError={(e) => { (e.target as HTMLImageElement).src = `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/Aatrox.png`; }}
                />
                <p className="text-[10px] text-gray-500">{p.champion_name}</p>
              </div>
              <span className="text-[9px] text-gray-600 italic">Sem histórico</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const SCORE_DIM_LABELS: Record<string, string> = {
  rank: 'Rank', season: 'Season', mastery: 'Mastery',
  champion: 'Champion', role_fit: 'Role Fit', momentum: 'Form',
};

const ROLE_ICONS: Record<string, string> = {
  top: '🛡️', jungle: '🌿', mid: '⚡', adc: '🏹', support: '💖',
};

function MatchupRow({ m, ddVersion }: { m: MatchupEntry; ddVersion: string }) {
  const myS = m.my_player;
  const enS = m.enemy_player;
  const maxScore = Math.max(myS.score, enS.score, 1);
  const myPct = Math.round((myS.score / maxScore) * 100);
  const enPct = Math.round((enS.score / maxScore) * 100);
  const isMineWinning = m.winner === 'my_team';
  const isEnemyWinning = m.winner === 'enemy_team';
  const isEven = m.winner === 'even';

  return (
    <div className="py-2.5 px-3 hover:bg-[#0f0f0f] transition-colors">
      {/* Role header */}
      <div className="flex items-center justify-center gap-1 mb-1.5">
        <span className="text-[10px]">{ROLE_ICONS[m.role] || '❓'}</span>
        <span className="text-[10px] text-gray-400 font-bold uppercase tracking-wider">
          {ROLE_LABELS[m.role] || m.role}
        </span>
      </div>

      {/* Players comparison */}
      <div className="flex items-center gap-2">
        {/* My player */}
        <div className={`flex-1 flex items-center gap-2 ${isMineWinning ? '' : 'opacity-70'}`}>
          <div className="flex items-center gap-1.5 flex-1 justify-end">
            <div className="text-right min-w-0">
              <p className={`text-[11px] font-semibold truncate ${isMineWinning ? 'text-blue-300' : 'text-gray-400'}`}>
                {myS.name.split('#')[0]}
              </p>
              <p className="text-[9px] text-gray-600">{myS.champion}</p>
            </div>
            <img
              src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${myS.champion}.png`}
              className={`w-8 h-8 rounded-lg border ${isMineWinning ? 'border-blue-500/50' : 'border-[#333]'}`}
              alt={myS.champion}
              onError={(e) => { (e.target as HTMLImageElement).src = `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/Aatrox.png`; }}
            />
          </div>
        </div>

        {/* Score comparison */}
        <div className="max-w-[90vw] w-[140px] shrink-0">
          {/* Score bars */}
          <div className="flex items-center gap-1">
            <div className="flex-1 h-2 bg-[#1a1a1a] rounded-full overflow-hidden flex justify-end">
              <div
                className={`h-full rounded-full transition-all ${isMineWinning ? 'bg-blue-500' : 'bg-blue-500/30'}`}
                style={{ width: `${myPct}%` }}
              />
            </div>
            <span className={`text-[10px] font-bold w-[28px] text-center ${
              isEven ? 'text-gray-400' : isMineWinning ? 'text-blue-400' : isEnemyWinning ? 'text-red-400' : 'text-gray-400'
            }`}>
              {isEven ? '=' : isMineWinning ? '◀' : '▶'}
            </span>
            <div className="flex-1 h-2 bg-[#1a1a1a] rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${isEnemyWinning ? 'bg-red-500' : 'bg-red-500/30'}`}
                style={{ width: `${enPct}%` }}
              />
            </div>
          </div>
          {/* Verdict */}
          <p className={`text-[8px] text-center mt-0.5 font-medium ${
            isEven ? 'text-gray-500' : isMineWinning ? 'text-blue-400/80' : 'text-red-400/80'
          }`}>
            {isEven ? 'Equilibrado' :
              m.verdict === 'clear' ? `${m.winner === 'my_team' ? '⬆️' : '⬇️'} Vantagem clara` :
              m.verdict === 'slight' ? `${m.winner === 'my_team' ? '↗️' : '↘️'} Ligeira vantagem` :
              'Equilibrado'}
          </p>
        </div>

        {/* Enemy player */}
        <div className={`flex-1 flex items-center gap-2 ${isEnemyWinning ? '' : 'opacity-70'}`}>
          <div className="flex items-center gap-1.5 flex-1">
            <img
              src={`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${enS.champion}.png`}
              className={`w-8 h-8 rounded-lg border ${isEnemyWinning ? 'border-red-500/50' : 'border-[#333]'}`}
              alt={enS.champion}
              onError={(e) => { (e.target as HTMLImageElement).src = `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/Aatrox.png`; }}
            />
            <div className="min-w-0">
              <p className={`text-[11px] font-semibold truncate ${isEnemyWinning ? 'text-red-300' : 'text-gray-400'}`}>
                {enS.name.split('#')[0]}
              </p>
              <p className="text-[9px] text-gray-600">{enS.champion}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Advantages tags */}
      {(m.advantages_mine.length > 0 || m.advantages_enemy.length > 0) && (
        <div className="flex items-center justify-center gap-2 mt-1">
          {m.advantages_mine.map((a, i) => (
            <span key={`m${i}`} className="text-[7px] px-1 py-px rounded bg-blue-500/10 text-blue-400">
              ◀ {a}
            </span>
          ))}
          {m.advantages_enemy.map((a, i) => (
            <span key={`e${i}`} className="text-[7px] px-1 py-px rounded bg-red-500/10 text-red-400">
              {a} ▶
            </span>
          ))}
        </div>
      )}

      {/* Score breakdown on hover — mini bars */}
      <div className="flex items-center gap-0.5 mt-1.5 justify-center">
        {(Object.keys(SCORE_DIM_LABELS) as Array<keyof typeof SCORE_DIM_LABELS>).map((dim) => {
          const myVal = myS.scores[dim as keyof typeof myS.scores];
          const enVal = enS.scores[dim as keyof typeof enS.scores];
          const better = myVal > enVal ? 'mine' : enVal > myVal ? 'enemy' : 'even';
          return (
            <div key={dim} className="flex flex-col items-center" title={`${SCORE_DIM_LABELS[dim]}: ${myVal} vs ${enVal}`}>
              <div className="flex gap-px">
                <div className={`w-1 rounded-full ${better === 'mine' ? 'bg-blue-500' : 'bg-[#222]'}`}
                  style={{ height: `${Math.max(2, myVal / 10)}px` }} />
                <div className={`w-1 rounded-full ${better === 'enemy' ? 'bg-red-500' : 'bg-[#222]'}`}
                  style={{ height: `${Math.max(2, enVal / 10)}px` }} />
              </div>
              <span className="text-[6px] text-gray-600 mt-px">{SCORE_DIM_LABELS[dim].slice(0, 3)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MatchupPanel({ analysis, ddVersion }: { analysis?: MatchupAnalysis; ddVersion: string }) {
  if (!analysis || !analysis.matchups?.length) return null;
  const s = analysis.summary;
  const totalDiff = s.my_team_score - s.enemy_team_score;
  const teamAdv = s.advantage;

  return (
    <div className="border-t border-[#1a1a1a]">
      {/* Summary header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#0a0a0a]">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-wider text-yellow-500">⚔️ Matchup Analysis</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-blue-400 font-bold">{s.lanes_won}</span>
            <span className="text-[8px] text-gray-600">won</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-gray-400 font-bold">{s.lanes_even}</span>
            <span className="text-[8px] text-gray-600">even</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-red-400 font-bold">{s.lanes_lost}</span>
            <span className="text-[8px] text-gray-600">lost</span>
          </div>
          <div className={`text-[10px] font-bold px-2 py-0.5 rounded ${
            teamAdv === 'my_team' ? 'bg-blue-500/15 text-blue-400' :
            teamAdv === 'enemy_team' ? 'bg-red-500/15 text-red-400' :
            'bg-gray-500/15 text-gray-400'
          }`}>
            {teamAdv === 'my_team' ? '⬆️ Vantagem Tua' :
             teamAdv === 'enemy_team' ? '⬇️ Vantagem Inimiga' :
             '🤝 Equilibrado'}
          </div>
        </div>
      </div>

      {/* Overall score bar */}
      <div className="px-4 py-1.5 bg-[#0a0a0a] border-b border-[#1a1a1a]">
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-blue-400 font-medium w-16 text-right">{s.my_team_score.toFixed(0)}</span>
          <div className="flex-1 h-2.5 bg-[#1a1a1a] rounded-full overflow-hidden flex">
            <div
              className="h-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all"
              style={{ width: `${Math.round(s.my_team_score / (s.my_team_score + s.enemy_team_score) * 100)}%` }}
            />
            <div
              className="h-full bg-gradient-to-r from-red-400 to-red-600 transition-all"
              style={{ width: `${Math.round(s.enemy_team_score / (s.my_team_score + s.enemy_team_score) * 100)}%` }}
            />
          </div>
          <span className="text-[9px] text-red-400 font-medium w-16">{s.enemy_team_score.toFixed(0)}</span>
        </div>
      </div>

      {/* Per-role matchups */}
      <div className="divide-y divide-[#151515]">
        {analysis.matchups.map((m) => (
          <MatchupRow key={m.role} m={m} ddVersion={ddVersion} />
        ))}
      </div>
    </div>
  );
}

/* ── Win Probability Bar ─────────────────────────────────────── */
function WinProbabilityBar({ wp }: { wp?: WinProbability }) {
  if (!wp) return null;
  const pct = Math.round(wp.probability);
  const enemyPct = 100 - pct;
  const color = pct >= 60 ? 'text-green-400' : pct >= 50 ? 'text-blue-400' : pct >= 40 ? 'text-orange-400' : 'text-red-400';
  const barColor = pct >= 60 ? 'from-green-600 to-green-400' : pct >= 50 ? 'from-blue-600 to-blue-400' : pct >= 40 ? 'from-orange-600 to-orange-400' : 'from-red-600 to-red-400';
  const confLabel = wp.confidence === 'high' ? 'Alta' : wp.confidence === 'medium' ? 'Média' : 'Baixa';

  return (
    <div className="px-4 py-3 bg-[#0a0a0a] border-b border-[#1a1a1a]">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-bold uppercase tracking-wider text-yellow-500">🤖 AI Prediction</span>
        <span className="text-[9px] text-gray-600">Confiança: {confLabel}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className={`text-lg font-black ${color} w-14 text-right`}>{pct}%</span>
        <div className="flex-1 h-4 bg-[#1a1a1a] rounded-full overflow-hidden flex">
          <div className={`h-full bg-gradient-to-r ${barColor} transition-all duration-500 rounded-l-full`} style={{ width: `${pct}%` }} />
          <div className="h-full bg-gradient-to-r from-red-400 to-red-600 transition-all duration-500 rounded-r-full" style={{ width: `${enemyPct}%` }} />
        </div>
        <span className="text-lg font-black text-red-400 w-14">{enemyPct}%</span>
      </div>
      {wp.factors.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-2 justify-center">
          {wp.factors.map((f, i) => (
            <span key={i} className={`text-[8px] px-1.5 py-0.5 rounded ${
              f.value > 0 ? 'bg-green-500/10 text-green-400' : f.value < 0 ? 'bg-red-500/10 text-red-400' : 'bg-gray-500/10 text-gray-400'
            }`}>
              {f.value > 0 ? '+' : ''}{f.value.toFixed(1)} {f.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Team Comp Detailed Panel ─────────────────────────────────── */
const SCALING_COLORS: Record<string, string> = {
  early: 'text-red-400', early_mid: 'text-orange-400', balanced: 'text-yellow-400',
  mid_late: 'text-blue-400', late: 'text-purple-400',
};

function TeamCompDetailedPanel({ myComp, enemyComp }: { myComp?: TeamCompAnalysis; enemyComp?: TeamCompAnalysis }) {
  if (!myComp && !enemyComp) return null;

  const renderComp = (comp: TeamCompAnalysis, color: 'blue' | 'red', label: string) => {
    const total = comp.ad_count + comp.ap_count + comp.mixed_count;
    return (
      <div className="flex-1 space-y-2">
        <p className={`text-[10px] font-bold uppercase tracking-wider ${color === 'blue' ? 'text-blue-400' : 'text-red-400'}`}>{label}</p>
        {/* Damage split bars */}
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-orange-400 w-5">AD</span>
            <div className="flex-1 h-1.5 bg-[#222] rounded-full overflow-hidden">
              <div className="h-full bg-orange-500 rounded-full transition-all" style={{ width: `${comp.ad_pct}%` }} />
            </div>
            <span className="text-[9px] text-gray-500 w-8 text-right">{comp.ad_pct}%</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-purple-400 w-5">AP</span>
            <div className="flex-1 h-1.5 bg-[#222] rounded-full overflow-hidden">
              <div className="h-full bg-purple-500 rounded-full transition-all" style={{ width: `${comp.ap_pct}%` }} />
            </div>
            <span className="text-[9px] text-gray-500 w-8 text-right">{comp.ap_pct}%</span>
          </div>
        </div>
        {/* Identity + Scaling */}
        <div className="flex flex-wrap gap-1">
          {comp.identities.map((id, i) => (
            <span key={i} className="text-[8px] px-1.5 py-0.5 bg-yellow-500/10 text-yellow-400 rounded font-medium">{id}</span>
          ))}
          <span className={`text-[8px] px-1.5 py-0.5 rounded font-medium bg-[#1a1a1a] ${SCALING_COLORS[comp.scaling] || 'text-gray-400'}`}>
            📈 {comp.scaling_label}
          </span>
        </div>
        {/* Archetypes */}
        <div className="flex flex-wrap gap-1">
          {Object.entries(comp.archetypes).map(([arch, count]) => (
            count > 0 && <span key={arch} className="text-[8px] px-1 py-0.5 bg-[#1a1a1a] text-gray-400 rounded capitalize">{arch} ×{count}</span>
          ))}
        </div>
        {/* Stats */}
        <div className="flex flex-wrap gap-1.5">
          {comp.has_tank && <span className="text-[8px] px-1 py-0.5 bg-blue-500/10 text-blue-400 rounded">🛡️ Tank</span>}
          {comp.has_engage && <span className="text-[8px] px-1 py-0.5 bg-green-500/10 text-green-400 rounded">⚔️ Engage ×{comp.engage_count}</span>}
          {comp.split_push > 0 && <span className="text-[8px] px-1 py-0.5 bg-amber-500/10 text-amber-400 rounded">🗡️ Split ×{comp.split_push}</span>}
          {comp.poke > 0 && <span className="text-[8px] px-1 py-0.5 bg-cyan-500/10 text-cyan-400 rounded">🎯 Poke ×{comp.poke}</span>}
        </div>
        {/* Warnings */}
        {comp.warnings.length > 0 && (
          <div className="space-y-0.5">
            {comp.warnings.map((w, i) => (
              <p key={i} className="text-[8px] text-red-400/80">⚠️ {w}</p>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="px-4 py-3 border-t border-[#1a1a1a] bg-[#0a0a0a]">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-yellow-500">🧩 Team Comp Analysis</span>
      </div>
      <div className="flex gap-4">
        {myComp && renderComp(myComp, 'blue', 'Tua Equipa')}
        <div className="w-px bg-[#222] shrink-0" />
        {enemyComp && renderComp(enemyComp, 'red', 'Equipa Inimiga')}
      </div>
    </div>
  );
}

/* ── Duo Detection ────────────────────────────────────────────── */
function DuoSection({ myDuos, enemyDuos }: { myDuos?: DuoDetection[]; enemyDuos?: DuoDetection[] }) {
  const hasDuos = (myDuos && myDuos.length > 0) || (enemyDuos && enemyDuos.length > 0);
  if (!hasDuos) return null;

  const renderDuo = (duo: DuoDetection, color: 'blue' | 'red') => (
    <div className={`flex items-center gap-1.5 px-2 py-1 rounded-lg ${color === 'blue' ? 'bg-blue-500/10' : 'bg-red-500/10'}`}>
      <span className="text-[10px]">👥</span>
      <span className={`text-[10px] font-medium ${color === 'blue' ? 'text-blue-300' : 'text-red-300'}`}>
        {duo.player1.split('#')[0]}
      </span>
      <span className="text-[8px] text-gray-600">+</span>
      <span className={`text-[10px] font-medium ${color === 'blue' ? 'text-blue-300' : 'text-red-300'}`}>
        {duo.player2.split('#')[0]}
      </span>
      <span className="text-[8px] text-gray-500 ml-1">({duo.games_together} jogos juntos)</span>
    </div>
  );

  return (
    <div className="px-4 py-2.5 border-t border-[#1a1a1a] bg-[#0a0a0a]">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[10px] font-bold uppercase tracking-wider text-yellow-500">👥 Duos Detetados</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {myDuos?.map((d, i) => <div key={`m${i}`}>{renderDuo(d, 'blue')}</div>)}
        {enemyDuos?.map((d, i) => <div key={`e${i}`}>{renderDuo(d, 'red')}</div>)}
      </div>
    </div>
  );
}

/* ── Head-to-Head Section ─────────────────────────────────────── */
function HeadToHeadSection({ encounters }: { encounters?: HeadToHead[] }) {
  if (!encounters || encounters.length === 0) return null;

  return (
    <div className="px-4 py-2.5 border-t border-[#1a1a1a] bg-[#0a0a0a]">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[10px] font-bold uppercase tracking-wider text-yellow-500">🔄 Já Jogaste Com/Contra</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {encounters.map((h, i) => (
          <div key={i} className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg ${
            h.current_relation === 'ally' ? 'bg-blue-500/10' : 'bg-red-500/10'
          }`}>
            <span className="text-[10px]">{h.current_relation === 'ally' ? '🤝' : '⚔️'}</span>
            <div>
              <p className={`text-[10px] font-medium ${h.current_relation === 'ally' ? 'text-blue-300' : 'text-red-300'}`}>
                {h.player_name.split('#')[0]} <span className="text-gray-500">({h.champion})</span>
              </p>
              <p className="text-[8px] text-gray-500">
                {h.games_with > 0 && <span className="text-blue-400">{h.games_with}× aliado</span>}
                {h.games_with > 0 && h.games_against > 0 && <span className="mx-0.5">/</span>}
                {h.games_against > 0 && <span className="text-red-400">{h.games_against}× inimigo</span>}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Strategic Advice Panel ─────────────────────────────────────── */
const TIP_PRIORITY_COLORS: Record<string, string> = {
  high: 'border-l-yellow-500 bg-yellow-500/5',
  medium: 'border-l-blue-500 bg-blue-500/5',
  low: 'border-l-gray-500 bg-gray-500/5',
};

function StrategicAdvicePanel({ tips }: { tips?: StrategicTip[] }) {
  if (!tips || tips.length === 0) return null;

  return (
    <div className="px-4 py-3 border-t border-[#1a1a1a] bg-[#0a0a0a]">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-yellow-500">💡 Dicas Estratégicas</span>
      </div>
      <div className="space-y-1">
        {tips.map((tip, i) => (
          <div key={i} className={`flex items-start gap-2 px-2.5 py-1.5 rounded-lg border-l-2 ${TIP_PRIORITY_COLORS[tip.priority] || TIP_PRIORITY_COLORS.low}`}>
            <span className="text-[11px] shrink-0 mt-px">{tip.icon}</span>
            <p className="text-[10px] text-gray-300 leading-relaxed">{tip.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function CompAnalysis({ label, comp, color }: { label: string; comp?: TeamComp; color: 'blue' | 'red' }) {
  if (!comp || (comp.ad_count === 0 && comp.ap_count === 0)) return null;
  const total = comp.ad_count + comp.ap_count + comp.mixed_count;
  const adPct = total > 0 ? Math.round((comp.ad_count / total) * 100) : 0;
  const apPct = total > 0 ? Math.round((comp.ap_count / total) * 100) : 0;

  return (
    <div className="bg-[#111] rounded-lg p-2.5">
      <p className={`text-[10px] font-medium mb-2 ${color === 'blue' ? 'text-blue-400' : 'text-red-400'}`}>{label}</p>
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-orange-400 w-6">AD</span>
          <div className="flex-1 h-1.5 bg-[#222] rounded-full overflow-hidden">
            <div className="h-full bg-orange-500 rounded-full" style={{ width: `${adPct}%` }} />
          </div>
          <span className="text-[10px] text-gray-500 w-6 text-right">{comp.ad_count}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-purple-400 w-6">AP</span>
          <div className="flex-1 h-1.5 bg-[#222] rounded-full overflow-hidden">
            <div className="h-full bg-purple-500 rounded-full" style={{ width: `${apPct}%` }} />
          </div>
          <span className="text-[10px] text-gray-500 w-6 text-right">{comp.ap_count}</span>
        </div>
        <div className="flex items-center gap-2 mt-1">
          {comp.has_tank && <span className="text-[9px] px-1 py-0.5 bg-blue-500/10 text-blue-400 rounded">Tank</span>}
          {comp.has_engage && <span className="text-[9px] px-1 py-0.5 bg-green-500/10 text-green-400 rounded">Engage</span>}
          {comp.cc_count > 0 && <span className="text-[9px] px-1 py-0.5 bg-yellow-500/10 text-yellow-400 rounded">CC ×{comp.cc_count}</span>}
        </div>
      </div>
    </div>
  );
}


/* ── AI Prediction Panel ─────────────────────────────────────── */

function AIPredictionPanel({ stats, history, calibration, onResolve }: {
  stats: any;
  history: any[];
  calibration: any;
  onResolve: () => void;
}) {
  if (!stats) return null;

  const hasData = stats.resolved > 0;
  const accuracy = stats.accuracy;
  const accColor = accuracy === null ? 'text-gray-400' :
    accuracy >= 65 ? 'text-green-400' : accuracy >= 50 ? 'text-yellow-400' : 'text-red-400';
  const accBg = accuracy === null ? 'from-gray-600 to-gray-500' :
    accuracy >= 65 ? 'from-green-600 to-green-400' : accuracy >= 50 ? 'from-yellow-600 to-yellow-400' : 'from-red-600 to-red-400';

  const confLevels = ['high', 'medium', 'low'];
  const confLabels: Record<string, string> = { high: 'Alta', medium: 'Média', low: 'Baixa' };
  const confColors: Record<string, string> = { high: 'text-green-400', medium: 'text-yellow-400', low: 'text-gray-400' };

  return (
    <div className="bg-[#161616] rounded-2xl border border-[#222] overflow-hidden">
      <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">🤖 AI Predictions</h3>
          <p className="text-xs text-gray-500 mt-0.5">{stats.total_predictions} previsões ({stats.resolved} resolvidas)</p>
        </div>
        {stats.unresolved > 0 && (
          <button onClick={onResolve}
            className="px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 rounded-lg text-[10px] font-medium transition-all">
            Resolver ({stats.unresolved})
          </button>
        )}
      </div>

      <div className="p-4 space-y-4">
        {/* Main accuracy display */}
        <div className="flex items-center justify-center gap-6">
          <div className="text-center">
            <p className={`text-3xl sm:text-4xl font-black ${accColor}`}>
              {hasData ? `${accuracy}%` : '—'}
            </p>
            <p className="text-[10px] text-gray-500 mt-1">Precisão</p>
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-gray-500 w-16">Corretas</span>
              <span className="text-xs font-bold text-green-400">{stats.correct}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-gray-500 w-16">Erradas</span>
              <span className="text-xs font-bold text-red-400">{stats.incorrect}</span>
            </div>
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-gray-500 w-16">Streak</span>
              <span className="text-xs font-bold text-yellow-400">🔥 {stats.recent_streak}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-gray-500 w-16">Best</span>
              <span className="text-xs font-bold text-purple-400">⭐ {stats.best_streak}</span>
            </div>
          </div>
        </div>

        {/* Accuracy bar */}
        {hasData && (
          <div className="h-3 bg-[#1a1a1a] rounded-full overflow-hidden">
            <div className={`h-full bg-gradient-to-r ${accBg} rounded-full transition-all duration-500`}
              style={{ width: `${accuracy}%` }} />
          </div>
        )}

        {/* By confidence level */}
        {hasData && Object.keys(stats.by_confidence).length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {confLevels.map(lvl => {
              const data = stats.by_confidence[lvl];
              if (!data) return (
                <div key={lvl} className="bg-[#111] rounded-xl p-2.5 text-center">
                  <p className={`text-[10px] font-bold uppercase ${confColors[lvl]}`}>{confLabels[lvl]}</p>
                  <p className="text-lg font-bold text-gray-600">—</p>
                </div>
              );
              return (
                <div key={lvl} className="bg-[#111] rounded-xl p-2.5 text-center">
                  <p className={`text-[10px] font-bold uppercase ${confColors[lvl]}`}>{confLabels[lvl]}</p>
                  <p className="text-lg font-bold">{data.accuracy}%</p>
                  <p className="text-[9px] text-gray-600">{data.correct}/{data.total}</p>
                </div>
              );
            })}
          </div>
        )}

        {/* Calibration */}
        {calibration && calibration.total >= 10 && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Calibração</p>
              <p className="text-[10px] text-gray-500">Brier: <span className={`font-bold ${(calibration.brier_score ?? 1) <= 0.2 ? 'text-green-400' : (calibration.brier_score ?? 1) <= 0.3 ? 'text-yellow-400' : 'text-red-400'}`}>{calibration.brier_score != null ? calibration.brier_score.toFixed(3) : 'N/A'}</span></p>
            </div>
            <div className="space-y-1">
              {calibration.bins.map((bin: any) => {
                if (bin.count === 0) return null;
                const barWidth = Math.max(4, bin.actual_winrate);
                const isGood = Math.abs(bin.deviation) <= 10;
                return (
                  <div key={bin.range} className="flex items-center gap-2">
                    <span className="text-[9px] text-gray-500 w-12 text-right">{bin.range}</span>
                    <div className="flex-1 h-3 bg-[#1a1a1a] rounded-full overflow-hidden relative">
                      <div className={`h-full rounded-full ${isGood ? 'bg-green-600/60' : 'bg-orange-600/60'}`}
                        style={{ width: `${barWidth}%` }} />
                      <div className="absolute top-0 h-full w-0.5 bg-white/30" style={{ left: `${bin.avg_predicted}%` }} />
                    </div>
                    <span className="text-[9px] text-gray-400 w-20">{bin.actual_winrate.toFixed(0)}% real ({bin.count})</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recent predictions */}
        {history.length > 0 && (
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-2">Últimas Previsões</p>
            <div className="space-y-1">
              {history.slice(0, 10).map((p: any) => (
                <div key={p.id} className="flex items-center gap-2 px-2 py-1.5 bg-[#111] rounded-lg">
                  <span className="text-sm w-5 text-center">
                    {p.actual_win === null ? '⏳' : p.correct ? '✅' : '❌'}
                  </span>
                  <span className="text-[10px] text-gray-400 w-16">{p.date}</span>
                  <span className="text-[10px] font-medium flex-1">
                    {p.champion_played || '?'} vs {p.champion_against || '?'}
                  </span>
                  <span className={`text-[10px] font-bold ${p.predicted_win ? 'text-green-400' : 'text-red-400'}`}>
                    {p.predicted_win ? 'WIN' : 'LOSS'} ({p.confidence}%)
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
