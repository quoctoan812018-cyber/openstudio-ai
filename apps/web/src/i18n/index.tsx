import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import en from "./en.json";
import vi from "./vi.json";

export type Lang = "vi" | "en";
const dicts: Record<Lang, Record<string, string>> = { vi, en };

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  let s = dicts[lang][key] ?? dicts.vi[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const Ctx = createContext<I18n>({ lang: "vi", setLang: () => {}, t: (k) => k });

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem("lang");
    if (saved === "vi" || saved === "en") return saved;
  } catch {
    /* localStorage có thể bị chặn */
  }
  return "vi";
}

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Lang }) {
  const [lang, setLangState] = useState<Lang>(initial ?? initialLang());
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    document.documentElement.lang = l;
    try {
      localStorage.setItem("lang", l);
    } catch {
      /* bỏ qua */
    }
  }, []);
  const value = useMemo<I18n>(() => ({ lang, setLang, t: (k, v) => translate(lang, k, v) }), [lang, setLang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
