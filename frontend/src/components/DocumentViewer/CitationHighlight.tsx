interface CitationHighlightProps {
  text: string;
  index: number;
}

export function CitationHighlight({ text, index }: CitationHighlightProps) {
  return (
    <div className="flex gap-2 mb-1.5">
      <span className="flex-shrink-0 w-5 h-5 bg-amber-200 text-amber-800 text-xs rounded-full flex items-center justify-center font-medium">
        {index}
      </span>
      <p className="text-sm text-gray-700 italic leading-relaxed">
        "{text}"
      </p>
    </div>
  );
}
