import { Copy, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { QuestionImageField } from "@/components/questions/question-image-field";
import { QuickAddOptions } from "@/components/questions/quick-add-options";
import {
  addOptionToBlankGroup, addSharedBlankOption, optionImageUrl, optionsToKeyValueList,
  reuseFirstBlankOption, updateBlankOptionText, updateOptionText,
} from "../question-option-editing";
import {
  extractBlankSlotIds, normalizeBlankOptionGroups, resolveBlankOptionGroupsValue,
} from "@/lib/question-options";
import { canonicalizeQuestionType } from "@/lib/question-types";
import type { AdminQuestion, QuestionEditRequest } from "@/lib/api/types";
import type { Dispatch, SetStateAction } from "react";

type Props = {
  editForm: QuestionEditRequest;
  editStemText: string;
  setEditForm: Dispatch<SetStateAction<QuestionEditRequest>>;
  selectedQuestionId: number;
  dirty: boolean;
  beforeDirtyMutation: () => Promise<boolean>;
  onMutated: (question: AdminQuestion) => void;
};

function BlankOptionGroup({
  group, firstGroupId, setEditForm,
}: {
  group: ReturnType<typeof normalizeBlankOptionGroups>[number];
  firstGroupId: string;
  setEditForm: Props["setEditForm"];
}) {
  return (
    <div key={group.id} className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <BlankOptionGroupHeader group={group} firstGroupId={firstGroupId} setEditForm={setEditForm} />
      {group.options.map((option) => (
        <BlankOptionRow key={`${group.id}-${option.key}`} groupId={group.id}
          option={option} setEditForm={setEditForm} />
      ))}
      <BlankOptionGroupFooter group={group} setEditForm={setEditForm} />
    </div>
  );
}

type BlankGroupProps = {
  group: ReturnType<typeof normalizeBlankOptionGroups>[number];
  firstGroupId: string;
  setEditForm: Props["setEditForm"];
};

function BlankOptionGroupHeader({ group, firstGroupId, setEditForm }: BlankGroupProps) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/70 px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="flex h-7 min-w-7 items-center justify-center rounded-md bg-slate-900 px-1.5 text-[11px] font-semibold text-white">{group.id}</span>
        <span className="text-xs font-medium text-slate-600">该空选项</span>
      </div>
      <div className="flex items-center gap-2">
        {group.id !== firstGroupId ? (
          <button type="button"
            className="inline-flex h-7 items-center gap-1 rounded-md border border-slate-200 bg-white px-2 text-[10px] font-medium text-slate-500 transition hover:border-slate-300 hover:text-slate-800"
            title={`用第一空（${firstGroupId}）的选项覆盖当前空位`}
            onClick={() => setEditForm((current) => reuseFirstBlankOption(current, group.id))}>
            <Copy className="h-3 w-3" />复用第一空
          </button>
        ) : null}
        <span className="text-[10px] text-slate-400">{group.options.length} 项</span>
      </div>
    </div>
  );
}

function BlankOptionRow({
  groupId, option, setEditForm,
}: {
  groupId: string;
  option: ReturnType<typeof normalizeBlankOptionGroups>[number]["options"][number];
  setEditForm: Props["setEditForm"];
}) {
  return (
    <div className="flex items-center gap-3 border-b border-slate-100 px-3 py-2.5">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-[11px] font-semibold text-slate-600">{option.key}</span>
      <input className="h-9 min-w-0 flex-1 border-0 bg-transparent px-1 text-sm text-slate-800 outline-none placeholder:text-slate-300 focus:ring-0"
        value={option.text ?? ""} placeholder="请输入选项内容"
        onChange={(event) => setEditForm((current) =>
          updateBlankOptionText(current, groupId, option.key, event.target.value))} />
    </div>
  );
}

function BlankOptionGroupFooter({
  group, setEditForm,
}: Pick<BlankGroupProps, "group" | "setEditForm">) {
  return (
    <div className="flex items-center justify-between gap-3 bg-slate-50/40 px-3 py-2.5">
      <span className="text-[10px] text-slate-400">自动使用下一个可用字母</span>
      <Button type="button" size="sm" variant="secondary"
        className="h-8 border-slate-200 bg-white px-3 text-xs shadow-none"
        disabled={group.options.length >= 26}
        onClick={() => setEditForm((current) => addOptionToBlankGroup(current, group.id))}>
        <Plus className="h-3.5 w-3.5" />添加选项
      </Button>
    </div>
  );
}

function BlankOptionsEditor({ props }: { props: Props }) {
  const groups = normalizeBlankOptionGroups(resolveBlankOptionGroupsValue(props.editForm.content));
  const totalOptions = groups.reduce((sum, group) => sum + group.options.length, 0);
  const inferredBlankIds = extractBlankSlotIds(props.editStemText);
  const canAddSharedOption = groups.length > 0 || inferredBlankIds.length > 0;
  return (
    <section className="border-b border-slate-200 py-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-slate-950">选项</p>
          <p className="mt-1 text-[11px] text-slate-400">按空位编辑分组选项；顶部按钮会向所有空位添加同一字母选项</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="mr-1 text-[11px] tabular-nums text-slate-400">{groups.length} 个空位 · {totalOptions} 个选项</span>
          {groups.length > 1 ? (
            <Button type="button" size="sm" variant="secondary" className="h-8 border-slate-200 bg-white px-3 text-xs shadow-none"
              disabled={groups[0].options.length === 0} title="用第一空的选项覆盖其余所有空位的选项"
              onClick={() => props.setEditForm((current) => reuseFirstBlankOption(current))}>
              <Copy className="h-3.5 w-3.5" />全部复用第一空
            </Button>
          ) : null}
          <Button type="button" size="sm" variant="secondary" className="h-8 border-slate-200 bg-white px-3 text-xs shadow-none"
            disabled={!canAddSharedOption || groups.some((group) => group.options.length >= 26)}
            onClick={() => props.setEditForm((current) => addSharedBlankOption(current, extractBlankSlotIds(props.editStemText)))}>
            <Plus className="h-3.5 w-3.5" />添加选项
          </Button>
        </div>
      </div>
      {groups.length === 0 ? (
        <div className="mb-3 rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 py-4 text-sm text-[var(--color-text-hint)]">
          {inferredBlankIds.length > 0
            ? `已从题干识别 ${inferredBlankIds.length} 个空位，点击“添加选项”创建分组选项。`
            : "未从题干识别到空位标记，请先使用（ ）、① 或 ___ 标记空位。"}
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((group) => <BlankOptionGroup key={group.id} group={group} firstGroupId={groups[0].id} setEditForm={props.setEditForm} />)}
        </div>
      )}
    </section>
  );
}

function RegularOptionsEditor({ props, isChoiceType }: { props: Props; isChoiceType: boolean }) {
  const options = optionsToKeyValueList(props.editForm.options);
  return (
    <section className="border-b border-slate-200 py-5">
      <div className="mb-4 flex items-end justify-between gap-4">
        <div><p className="text-sm font-semibold text-slate-950">选项</p><p className="mt-1 text-[11px] text-slate-400">逐项编辑文字或补充选项图片</p></div>
        <span className="text-[11px] tabular-nums text-slate-400">{options.length} 个选项</span>
      </div>
      {options.length === 0 ? <p className="mb-3 text-sm text-[var(--color-text-hint)]">暂无可编辑选项</p> : (
        <div className="mb-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
          {options.map((option, index) => {
            const imageUrl = optionImageUrl(props.editForm.options, option.key);
            return (
              <div key={index} className="flex items-center gap-3 border-b border-slate-100 px-3 py-2.5 last:border-b-0">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-[11px] font-semibold text-slate-600">{option.key}</span>
                <input className="h-9 min-w-0 flex-1 border-0 bg-transparent px-1 text-sm text-slate-800 outline-none placeholder:text-slate-300 focus:ring-0"
                  value={option.text}
                  onChange={(event) => props.setEditForm({
                    ...props.editForm,
                    options: updateOptionText(props.editForm.options, option.key, event.target.value),
                  })}
                />
                <QuestionImageField questionId={props.selectedQuestionId} target={`option:${option.key}`} valueUrl={imageUrl}
                  canDelete={!!imageUrl} addLabel="上传图片" dirty={props.dirty}
                  beforeDirtyMutation={props.beforeDirtyMutation} variant="row" onMutated={props.onMutated} />
              </div>
            );
          })}
        </div>
      )}
      <QuickAddOptions questionId={props.selectedQuestionId} existingKeys={options.map(({ key }) => key)}
        disabled={!isChoiceType} dirty={props.dirty} beforeDirtyMutation={props.beforeDirtyMutation}
        onMutated={props.onMutated} />
    </section>
  );
}

export function QuestionOptionEditor(props: Props) {
  const type = canonicalizeQuestionType(props.editForm.question_type ?? "");
  if (type === "multi_blank_choice" || type === "multi_blank_multiple_choice") {
    return <BlankOptionsEditor props={props} />;
  }
  return <RegularOptionsEditor props={props} isChoiceType={type === "single_choice" || type === "multiple_choice"} />;
}
