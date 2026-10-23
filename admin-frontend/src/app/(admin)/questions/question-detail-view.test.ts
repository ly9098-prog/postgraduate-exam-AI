import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AdminQuestion } from "@/lib/api/types";
import { QuestionDetailView } from "./question-detail-view";

const question: AdminQuestion = {
  id: 7,
  question_type: "single_choice",
  content: { stem: "question stem" },
  options: { A: "yes", B: "no" },
  answer: "A",
  analysis: "answer analysis",
  knowledge_points: ["operating systems"],
  difficulty: 4,
  review_status: "approved",
  is_active: true,
};

function render(overrides: Partial<AdminQuestion>) {
  return renderToStaticMarkup(createElement(QuestionDetailView, {
    question: { ...question, ...overrides },
  }));
}

describe("QuestionDetailView", () => {
  it("renders the primary question sections and normalized options", () => {
    const html = render({});

    expect(html).toContain("question stem");
    expect(html).toContain("yes");
    expect(html).toContain("answer analysis");
    expect(html).toContain("operating systems");
    expect(html).not.toContain("其他题目图片");
  });

  it("renders only legacy images that are not already structured content", () => {
    const html = render({
      content: {
        stem: "stem",
        segments: [{ type: "text", text: "stem" }],
      },
      image_url: [{ url: "/legacy.png" }],
    });

    expect(html).toContain('src="/legacy.png"');
    expect(html).toContain("其他题目图片");
  });

  it("does not duplicate a legacy image already rendered by structured content", () => {
    const html = render({
      content: {
        stem: "stem",
        segments: [{ type: "text", text: "stem" }, { type: "image", url: "/same.png" }],
      },
      image_url: [{ url: "/same.png" }],
    });

    expect(html).not.toContain("其他题目图片");
    expect(html.match(/src="\/same\.png"/g)).toHaveLength(1);
  });
});
