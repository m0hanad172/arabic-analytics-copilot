import { create } from "zustand";

export type HistoryItem = {
  id: string;
  createdAt: number;
  source: "text" | "voice";
  question: string;
  responseMeta?: any;
  plan?: any;
  sql?: string;
};

type State = {
  items: HistoryItem[];
  add: (it: Omit<HistoryItem, "id" | "createdAt">) => void;
  clear: () => void;
};

export const useHistoryStore = create<State>((set) => ({
  items: [],
  add: (it) =>
    set((s) => ({
      items: [
        { id: crypto.randomUUID(), createdAt: Date.now(), ...it },
        ...s.items,
      ].slice(0, 50),
    })),
  clear: () => set({ items: [] }),
}));
