import "@tanstack/react-table";
import type { FilterFn } from "@tanstack/react-table";

declare module "@tanstack/react-table" {
  interface FilterFns {
    fuzzy: FilterFn<any>;
    numRange: FilterFn<any>;
  }
}
