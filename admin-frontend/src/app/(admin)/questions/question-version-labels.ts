import type { QuestionVersionSelection } from "@/components/questions/question-version-picker";
import type { QuestionVersionDetail } from "@/lib/api/types";

export type VersionDetailMap = {
  base: QuestionVersionSelection;
  compare: QuestionVersionSelection | null;
  baseDetail: { data?: QuestionVersionDetail | null; isFetching: boolean };
  compareDetail: { data?: QuestionVersionDetail | null; isFetching: boolean };
};

export function buildVersionLabels(map: VersionDetailMap) {
  const { base, compare, baseDetail, compareDetail } = map;
  const baseVersionLabel =
    base === "current"
      ? "当前版本"
      : baseDetail.data?.version
        ? `v${baseDetail.data.version}`
        : `v${base}`;
  const compareVersionLabel =
    compare === "current"
      ? "当前版本"
      : compare === null
        ? "请选择版本"
        : compareDetail.data?.version
          ? `v${compareDetail.data.version}`
          : `v${compare}`;
  const versionComparisonLoading =
    (typeof base === "number" && baseDetail.isFetching) ||
    (typeof compare === "number" && compareDetail.isFetching);
  const pendingVersionLabel =
    typeof base === "number" && baseDetail.isFetching
      ? `v${base}`
      : typeof compare === "number" && compareDetail.isFetching
        ? `v${compare}`
        : null;
  return { baseVersionLabel, compareVersionLabel, versionComparisonLoading, pendingVersionLabel };
}
