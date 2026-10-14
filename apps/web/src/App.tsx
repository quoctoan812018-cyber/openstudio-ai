import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { ConnectionGate } from "./api/connection";
import { I18nProvider, useI18n } from "./i18n";
import { Dashboard } from "./pages/Dashboard";
import { Library } from "./pages/Library";
import { Subtitles } from "./pages/Subtitles";
import { Dubbing } from "./pages/Dubbing";
import { TextToSpeech } from "./pages/TextToSpeech";
import { Highlights } from "./pages/Highlights";
import { Avatar } from "./pages/Avatar";
import { Campaign } from "./pages/Campaign";
import { Editor } from "./pages/Editor";
import { Thumbnail } from "./pages/Thumbnail";
import { Podcast } from "./pages/Podcast";
import { Agent } from "./pages/Agent";
import { Skills } from "./pages/Skills";
import { Settings } from "./pages/Settings";

function Shell() {
  const { t } = useI18n();
  const link = ({ isActive }: { isActive: boolean }) =>
    `block rounded px-3 py-2 ${isActive ? "bg-indigo-600 text-white" : "hover:bg-zinc-200 dark:hover:bg-zinc-800"}`;
  return (
    <div className="flex min-h-screen">
      <nav className="w-52 shrink-0 border-r border-zinc-200 p-4 dark:border-zinc-800">
        <div className="mb-6 text-lg font-bold">{t("app.name")}</div>
        <NavLink to="/" end className={link}>{t("nav.dashboard")}</NavLink>
        <NavLink to="/tools/subtitles" className={link}>{t("nav.subtitles")}</NavLink>
        <NavLink to="/tools/tts" className={link}>{t("nav.tts")}</NavLink>
        <NavLink to="/tools/dubbing" className={link}>{t("nav.dubbing")}</NavLink>
        <NavLink to="/tools/highlights" className={link}>{t("nav.highlights")}</NavLink>
        <NavLink to="/tools/podcast" className={link}>{t("nav.podcast")}</NavLink>
        <NavLink to="/tools/avatar" className={link}>{t("nav.avatar")}</NavLink>
        <NavLink to="/tools/editor" className={link}>{t("nav.editor")}</NavLink>
        <NavLink to="/tools/thumbnail" className={link}>{t("nav.thumbnail")}</NavLink>
        <NavLink to="/tools/campaign" className={link}>{t("nav.campaign")}</NavLink>
        <NavLink to="/tools/agent" className={link}>{t("nav.agent")}</NavLink>
        <NavLink to="/skills" className={link}>{t("nav.skills")}</NavLink>
        <NavLink to="/library" className={link}>{t("nav.library")}</NavLink>
        <NavLink to="/settings" className={link}>{t("nav.settings")}</NavLink>
      </nav>
      <main className="flex-1 p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/tools/subtitles" element={<Subtitles />} />
          <Route path="/tools/tts" element={<TextToSpeech />} />
          <Route path="/tools/dubbing" element={<Dubbing />} />
          <Route path="/tools/highlights" element={<Highlights />} />
          <Route path="/tools/podcast" element={<Podcast />} />
          <Route path="/tools/avatar" element={<Avatar />} />
          <Route path="/tools/editor" element={<Editor />} />
          <Route path="/tools/thumbnail" element={<Thumbnail />} />
          <Route path="/tools/campaign" element={<Campaign />} />
          <Route path="/tools/agent" element={<Agent />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/library" element={<Library />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

export function App() {
  // HashRouter: chạy được cả khi Electron nạp bản build qua file://
  return (
    <I18nProvider>
      <ConnectionGate>
        <HashRouter>
          <Shell />
        </HashRouter>
      </ConnectionGate>
    </I18nProvider>
  );
}
