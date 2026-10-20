import { useRef, useState, type DragEvent } from "react";
import { moveSegment, type SegmentData } from "@/lib/segment-utils";

export function useReviewSegmentDrag(segments: SegmentData[] | null, onChange: (next: SegmentData[]) => void) {
  const sourceIndex = useRef(-1);
  const [dragIndex, setDragIndex] = useState(-1);
  const [overIndex, setOverIndex] = useState(-1);
  const end = () => {
    setDragIndex(-1);
    setOverIndex(-1);
  };
  return {
    dragIndex,
    overIndex,
    start: (index: number, event: DragEvent) => {
      sourceIndex.current = index;
      setDragIndex(index);
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
    },
    over: (index: number, event: DragEvent) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      if (sourceIndex.current !== index) setOverIndex(index);
    },
    leave: () => setOverIndex(-1),
    drop: (index: number, event: DragEvent) => {
      event.preventDefault();
      const from = sourceIndex.current;
      end();
      if (from >= 0 && index >= 0 && from !== index && segments) {
        onChange(moveSegment(segments, from, index));
      }
    },
    end,
  };
}
