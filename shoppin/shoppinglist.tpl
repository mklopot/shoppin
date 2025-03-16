<html>
<head>
<style>
a:visited{
  color:blue;
}

a{
text-decoration: none
}

table, th, td {
  border: 1px dotted lightgray;
  border-collapse: collapse;
}
th, td {
  padding: 10px;
}
span.attribution{
  font-style: italic;
  font-size: 13px;
  color: gray;
}

</style>
</head>
<body>
  <h1>Shopping List</h1>
% if need:
  <h2>To Get</h2>
  <table style="width:50%">
  % for item in need:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{', '.join([ingredient.attribution.name for ingredient in item.ingredients])}}</span>
    % if item.optional:
         <br>&nbsp;&nbsp;optional
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
     </td>
     <td style="width:10%"><a href="/got/{{item.id}}">Got it!</a></td>
     <td style="width:10%"><a href="/have/{{item.id}}">Have it!</a></td>
  </tr>
  % end
</table>
% end

% if got:
  <h2>Got</h2>
  <table style="width:50%">
  % for item in got:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{', '.join([ingredient.attribution.name for ingredient in item.ingredients])}}</span>
    % if item.optional:
         <br>&nbsp;&nbsp;optional
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
     </td>
  </tr>
  % end
</table>
% end

% if have:
  <h2>Already Have</h2>
  <table style="width:50%">
  % for item in have:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{', '.join([ingredient.attribution.name for ingredient in item.ingredients])}}</span>
    % if item.optional:
         <br>&nbsp;&nbsp;optional
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
     </td>
     <td style="width:10%"><a href="/need/{{item.id}}">Need it!</a></td>
  </tr>
  % end
</table>
% end

</body>
</html>
