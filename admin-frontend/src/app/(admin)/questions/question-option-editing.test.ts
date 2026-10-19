import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { QuestionOptionEditor } from "./components/question-option-editor";
import {
  addOptionToBlankGroup,
  addSharedBlankOption,
  blankOptionGroupsStorageField,
  optionImageUrl,
  optionsToKeyValueList,
  optionStorageKey,
  reuseFirstBlankOption,
  updateBlankOptionText,
  updateOptionText,
} from "./question-option-editing";

describe("question option editing rules", () => {
  it("retains legacy blank group storage while adding and editing options", () => {
    const form = {
      content: {
        blank_groups: [{ id: "1", options: [{ key: "A", text: "old" }] }],
      },
    };
    expect(blankOptionGroupsStorageField(form.content)).toBe("blank_groups");
    const added = addSharedBlankOption(form, ["1", "2"]);
    const addedGroups = added.content?.blank_groups as Array<{ options: unknown[] }>;
    expect(addedGroups[0].options).toHaveLength(2);
    const edited = updateBlankOptionText(added, "1", "A", "new");
    const editedGroups = edited.content?.blank_groups as Array<{ options: Array<{ text: string }> }>;
    expect(editedGroups[0].options[0].text).toBe("new");
    expect(edited.content?.blank_option_groups).toBeUndefined();
  });

  it("preserves canonical precedence, group metadata, and reuse semantics", () => {
    const form = {
      content: {
        blank_option_groups: [
          { id: "1", label: "first", options: [{ key: "A", text: "x" }] },
          { id: "2", options: [{ key: "B", text: "y" }] },
        ],
        blank_groups: [{ id: "3", options: [{ key: "C", text: "z" }] }],
      },
    };
    const added = addOptionToBlankGroup(form, "1");
    const groups = added.content?.blank_option_groups as Array<{ label?: string; options: unknown[] }>;
    expect(groups[0].label).toBe("first");
    const reused = reuseFirstBlankOption(added, "2").content?.blank_option_groups as
      Array<{ options: unknown[] }>;
    expect(reused[1].options).toEqual(groups[0].options);
  });

  it("keeps normalized labels separate from their original storage keys", () => {
    const options = { " a ": { text: "old", image_url: "/a.png", extra: 7 } };
    expect(optionsToKeyValueList(options)).toEqual([{ key: " A ", text: "old" }]);
    expect(optionStorageKey(options, "A")).toBe(" a ");
    expect(optionImageUrl(options, "A")).toBe("/a.png");
    expect(updateOptionText(options, "A", "new")).toEqual({
      " a ": { text: "new", image_url: "/a.png", extra: 7 },
    });
  });

  it("renders the existing regular and grouped option editor branches", () => {
    const props = {
      editForm: {
        question_type: "single_choice",
        options: { A: { text: "Alpha", image_url: "/alpha.png" } },
      },
      editStemText: "",
      setEditForm: () => undefined,
      selectedQuestionId: 1,
      dirty: false,
      beforeDirtyMutation: async () => true,
      onMutated: () => undefined,
    };
    const regular = renderToStaticMarkup(createElement(QuestionOptionEditor, props));
    expect(regular).toContain("Alpha");
    expect(regular).toContain("逐项编辑文字或补充选项图片");
    const grouped = renderToStaticMarkup(createElement(QuestionOptionEditor, {
      ...props,
      editForm: {
        question_type: "multi_blank_choice",
        content: {
          blank_option_groups: [{ id: "①", options: [{ key: "A", text: "first" }] }],
        },
      },
    }));
    expect(grouped).toContain("按空位编辑分组选项");
    expect(grouped).toContain("①");
  });
});
